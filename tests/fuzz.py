#!/usr/bin/env python3
"""Random differential tests.

Each case is a random program built as a small syntax tree, printed twice:

  * in msed syntax (; between commands, \\; in text, $-N, $N, f F Z C ...)
  * as a plain GNU sed script that should do the same thing.  The msed-only
    commands are spelled out with ordinary sed commands, written
    independently of part 1's translator (different labels, T instead of t,
    z + s/^/.../ for C, and so on), and $-N / $N are resolved here.

Then GNU sed runs the second form, and part 1 (csh) and part 2 (awk) run
the first.  Standard output, exit status and every file written by w/W
must agree.

    tests/fuzz.py [--cases N] [--seed S] [--std]

--std leaves out the msed-only features, so the check is directly against
GNU sed's behaviour.
"""

import argparse
import os
import random
import resource
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSH = ["csh", "-f", os.path.join(ROOT, "part1-csh", "msed")]
AWK = [os.path.join(ROOT, "part2-awk", "msed")]
ENV = dict(os.environ, LC_ALL="C")


class Gen:
    def __init__(self, rng, ext):
        self.r = rng
        self.ext = ext
        self.labels = 0
        self.pending = []      # labels defined at the end of the program
        self.args = []         # $2, $3, ... values

    def pick(self, *weighted):
        items = [w[1] for w in weighted]
        weights = [w[0] for w in weighted]
        return self.r.choices(items, weights)[0]

    # ------------------------------------------------------------ pieces
    def regex(self):
        r = self.r
        atoms = ["a", "b", "c", ".", "[ab]", "[^a]", "x", "A"]
        out = ""
        groups = 0
        if r.random() < 0.2:
            out += "^"
        for _ in range(r.randint(1, 3)):
            if r.random() < 0.2:
                inner = r.choice(atoms) + r.choice(["", "*"])
                out += "\\(" + inner + "\\)"
                groups += 1
            else:
                out += r.choice(atoms)
            out += self.pick((6, ""), (2, "*"), (1, "\\+"), (1, "\\?"), (1, "\\{1,2\\}"))
        if r.random() < 0.1:
            out += "\\|" + r.choice(atoms)
        if r.random() < 0.2:
            out += "$"
        return out, groups

    def replacement(self, groups):
        r = self.r
        parts = []
        for _ in range(r.randint(0, 3)):
            choices = [(4, "X"), (2, "&"), (1, "\\n"), (1, "\\U"), (1, "\\L"), (1, "\\l"),
                       (1, "\\E"), (1, "\\u"), (1, "-")]
            if groups:
                choices.append((3, "\\%d" % r.randint(1, groups)))
            parts.append(self.pick(*choices))
        return "".join(parts)

    def text(self):
        """Text of a i c C: (value, msed spelling, GNU one-liner spelling)."""
        r = self.r
        val = r.choice("xyz") + "".join(r.choice("xyz &/;") for _ in range(r.randint(0, 4)))
        val = val.rstrip(" ")
        msed = val.replace("\\", "\\\\").replace(";", "\\;")
        gnu = val.replace("\\", "\\\\")
        return val, msed, gnu

    def address(self):
        r = self.r
        kinds = [(4, None), (3, "num"), (1, "last"), (2, "re"), (3, "range"), (1, "step")]
        if self.ext:
            kinds.append((3, "neg"))
        k = self.pick(*kinds)
        if k is None:
            return None
        if k == "num":
            return ("num", self.arg(str(r.randint(1, 5))))
        if k == "last":
            return ("last",)
        if k == "neg":
            return ("neg", r.randint(0, 4))
        if k == "re":
            return ("re", self.arg(self.regex()[0]))
        if k == "step":
            return ("step", r.randint(0, 3), r.randint(0, 3))
        a1 = self.pick((3, "num"), (3, "re"), (1, "zero"), (2, "neg") if self.ext else (0, "num"))
        if a1 == "num":
            a1 = ("num", r.randint(1, 5))
        elif a1 == "re":
            a1 = ("re", self.regex()[0])
        elif a1 == "neg":
            a1 = ("neg", r.randint(0, 4))
        else:
            return ("range", ("zero",), ("re", self.regex()[0]))
        a2 = self.pick((3, "num"), (3, "re"), (1, "last"), (1, "plus"), (1, "tilde"),
                       (2, "neg") if self.ext else (0, "num"))
        if a2 == "num":
            a2 = ("num", r.randint(0, 6))
        elif a2 == "re":
            a2 = ("re", self.regex()[0])
        elif a2 == "last":
            a2 = ("last",)
        elif a2 == "plus":
            a2 = ("plus", r.randint(0, 3))
        elif a2 == "tilde":
            a2 = ("tilde", r.randint(1, 3))
        else:
            a2 = ("neg", r.randint(0, 4))
        return ("range", a1, a2)

    def arg(self, value):
        """Sometimes pass a field as an argument: msed sees $N there."""
        if not self.ext or value == "" or self.r.random() > 0.15:
            return value
        self.args.append(value)
        return ("ARG", len(self.args) + 1, value)

    def command(self, depth):
        r = self.r
        ops = [(4, "s"), (3, "p"), (1, "P"), (2, "d"), (1, "D"), (1, "n"), (2, "N"),
               (1, "g"), (1, "G"), (1, "h"), (1, "H"), (1, "x"), (1, "="), (1, "z"),
               (1, "y"), (2, "a"), (1, "i"), (1, "c"), (1, "l"), (1, "q"), (1, "Q"),
               (2, "branch"), (1, "w"), (1, "r")]
        if depth < 2:
            ops.append((2, "block"))
        if self.ext:
            ops += [(3, "f"), (3, "F"), (3, "Z"), (3, "C"), (2, "W"), (2, "D")]
        op = self.pick(*ops)
        addr = self.address()
        neg = addr is not None and r.random() < 0.2
        if op == "s":
            rx, groups = self.regex()
            repl = self.replacement(groups)
            flags = self.pick((4, ""), (2, "g"), (1, "2"), (1, "2g"), (1, "p"), (1, "I"), (1, "w wf1"))
            return (addr, neg, "s", self.arg(rx), self.arg(repl), flags)
        if op in ("a", "i", "c", "C"):
            val, ms, gnu = self.text()
            v = self.arg(val)
            if isinstance(v, tuple):
                return (addr, neg, op, (val, v, gnu))
            return (addr, neg, op, (val, ms, gnu))
        if op in ("q", "Q"):
            return (addr if addr is None or addr[0] != "range" else None, neg, op, r.choice(["", "3"]))
        if op == "l":
            return (addr, neg, "l", r.choice(["", " 5", " 0"]))
        if op == "y":
            return (addr, neg, "y")
        if op == "branch":
            self.labels += 1
            name = "L%d" % self.labels
            self.pending.append(name)
            return (addr, neg, r.choice("btT"), name)
        if op in ("w", "W"):
            return (addr, neg, op, r.choice(["wf1", "wf2"]))
        if op == "r":
            return (addr, neg, "r")
        if op == "block":
            body = [self.command(depth + 1) for _ in range(r.randint(1, 3))]
            return (addr, neg, "block", body)
        return (addr, neg, op)

    def program(self):
        cmds = [self.command(0) for _ in range(self.r.randint(1, 5))]
        return cmds


# ------------------------------------------------------------------ printing

def F(x, msed):
    """A field: plain text, or ("ARG", n, value) printed as $n for msed."""
    if isinstance(x, tuple):
        return "$%d" % x[1] if msed else x[2]
    return str(x)


def addr_text(a, nlines, msed, end=False):
    if a is None:
        return ""
    k = a[0]
    if k == "num":
        return F(a[1], msed)
    if k == "last":
        return "$"
    if k == "zero":
        return "0"
    if k == "re":
        return "/" + F(a[1], msed) + "/"
    if k == "step":
        return "%d~%d" % (a[1], a[2])
    if k == "plus":
        return "+%d" % a[1]
    if k == "tilde":
        return "~%d" % a[1]
    if k == "neg":
        if msed:
            return "$-%d" % a[1]
        v = nlines - a[1]
        if not end and v < 1:
            v = nlines + 1
        if end and v < 0:
            v = 0
        return str(v)
    if k == "range":
        return addr_text(a[1], nlines, msed) + "," + addr_text(a[2], nlines, msed, end=True)
    raise ValueError(a)


class Printer:
    def __init__(self, nlines):
        self.n = nlines
        self.lab = 0

    def label(self):
        self.lab += 1
        return "oq%d" % self.lab

    def keepflag(self, a, op_lines):
        """GNU lines that run op_lines without changing the t flag."""
        la, lb = self.label(), self.label()
        return ([a + "{", "T " + la] + op_lines + ["s/$//", "b " + lb, ":" + la]
                + op_lines + ["T " + lb, ":" + lb, "}"])

    def cmd(self, c, msed):
        """One command: msed text (a string) or GNU lines (a list)."""
        addr, neg, op = c[0], c[1], c[2]
        a = addr_text(addr, self.n, msed) + ("!" if neg else "")
        if op == "s":
            line = a + "s/%s/%s/%s" % (F(c[3], msed), F(c[4], msed), c[5])
            return line if msed else [line]
        if op in ("a", "i", "c"):
            val, ms, gnu = c[3]
            return a + op + " " + F(ms, True) if msed else [a + op + " " + gnu]
        if op == "C":
            val, ms, gnu = c[3]
            if msed:
                return a + "C " + F(ms, True)
            esc = val.replace("\\", "\\\\").replace("&", "\\&").replace("/", "\\/")
            return self.keepflag(a, ["z", "s/^/%s/" % esc])
        if op == "f":
            return a + "f" if msed else [a + "s/$//"]
        if op == "F":
            if msed:
                return a + "F"
            la = self.label()
            return [a + "{", "T " + la, ":" + la, "}"]
        if op == "Z":
            if msed:
                return a + "Z"
            return self.keepflag(a, ["/\\n/!z", "s/^[^\\n]*\\n//"])
        if op in ("q", "Q", "l"):
            return a + op + c[3] if msed else [a + op + c[3]]
        if op == "y":
            return a + "y/abc/bca/" if msed else [a + "y/abc/bca/"]
        if op in ("b", "t", "T"):
            return a + op + " " + c[3] if msed else [a + op + " " + c[3]]
        if op in ("w", "W"):
            return a + op + " " + c[3] if msed else [a + op + " " + c[3]]
        if op == "r":
            return a + "r rf" if msed else [a + "r rf"]
        if op == "block":
            if msed:
                return a + "{" + ";".join(self.cmd(b, True) for b in c[3]) + ";}"
            lines = [a + "{"]
            for b in c[3]:
                lines += self.cmd(b, False)
            return lines + ["}"]
        return a + op if msed else [a + op]

    def program(self, cmds, labels, msed):
        if msed:
            return ";".join([self.cmd(c, True) for c in cmds] + [":" + l for l in labels])
        lines = []
        for c in cmds:
            lines += self.cmd(c, False)
        return "\n".join(lines + [":" + l for l in labels]) + "\n"


# ---------------------------------------------------------------- running

def limit_output():
    """A runaway program (G;D and friends) is stopped at 1 MB of output."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))


def run(argv, inp, cwd):
    """(status, stdout, files), or None if it loops or floods the output."""
    out_path = os.path.join(cwd, ".stdout")
    with open(out_path, "wb") as out:
        try:
            p = subprocess.run(argv, input=inp, cwd=cwd, env=ENV, stdout=out,
                               stderr=subprocess.DEVNULL, timeout=10,
                               preexec_fn=limit_output)
        except subprocess.TimeoutExpired:
            return None
    if os.path.getsize(out_path) > 100000:
        return None
    stdout = open(out_path, "rb").read()
    files = {}
    for f in ("wf1", "wf2"):
        path = os.path.join(cwd, f)
        if os.path.exists(path):
            files[f] = open(path, "rb").read()
    return (p.returncode, stdout, files)


def make_input(rng):
    lines = ["".join(rng.choice("abcA") for _ in range(rng.randint(0, 4)))
             for _ in range(rng.randint(0, 6))]
    s = "\n".join(lines)
    if lines and rng.random() < 0.85:
        s += "\n"
    return s.encode()


def one_case(job):
    """Build case n and run it everywhere.  Returns (n, report or None, stats)."""
    n, seed, ext = job
    rng = random.Random(seed * 1000003 + n)
    gen = Gen(rng, ext)
    cmds = gen.program()
    inp = make_input(rng)
    nlines = inp.count(b"\n") + (1 if inp and not inp.endswith(b"\n") else 0)
    msed_prog = Printer(nlines).program(cmds, gen.pending, True)
    gnu_prog = Printer(nlines).program(cmds, gen.pending, False)

    results = {}
    for name, argv in (("sed", None), ("csh", CSH), ("awk", AWK)):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "rf"), "w") as f:
            f.write("R1\nR2\n")
        if name == "sed":
            with open(os.path.join(d, "script.sed"), "w") as f:
                f.write(gnu_prog)
            res = run(["sed", "-f", "script.sed"], inp, d)
        else:
            res = run(argv + [msed_prog] + gen.args, inp, d)
        shutil.rmtree(d)
        results[name] = res
        if name == "sed" and res is None:
            return n, None, "skip"     # GNU sed itself loops (G;D and friends)

    ref = results["sed"]
    stat = "error" if ref[0] != 0 else ("output" if ref[1] else "empty")
    lines = []
    for name in ("csh", "awk"):
        got = results[name]
        same = got is not None and got == ref
        # an error is an error: the messages and exact codes may differ
        if got is not None and ref[0] != 0 and got[0] != 0 and not ref[1] and not got[1]:
            same = True
        if not same:
            lines += ["=" * 70,
                      "case %d (seed %d): %s differs from GNU sed" % (n, seed, name),
                      "msed program: %r  args: %r" % (msed_prog, gen.args),
                      "sed script:\n" + gnu_prog,
                      "input: %r" % inp,
                      "sed: %r" % (ref,),
                      "%s: %r" % (name, got)]
    return n, "\n".join(lines) if lines else None, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--std", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    opt = ap.parse_args()

    import multiprocessing
    jobs = [(n, opt.seed, not opt.std) for n in range(opt.cases)]
    counts = {"skip": 0, "error": 0, "output": 0, "empty": 0}
    bad = 0
    with multiprocessing.Pool(opt.jobs) as pool:
        for n, report, stat in pool.imap_unordered(one_case, jobs):
            counts[stat] += 1
            if report:
                bad += 1
                print(report)
    ran = opt.cases - counts["skip"]
    print("%s: %d cases run (%d ended in an error, %d printed something), %d differences"
          % ("std" if opt.std else "ext", ran, counts["error"], counts["output"], bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
