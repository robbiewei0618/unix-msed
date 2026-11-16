# msed — sed with extra commands, in C shell and in awk

[![CI](https://github.com/robbiewei0618/unix-msed/actions/workflows/ci.yml/badge.svg)](https://github.com/robbiewei0618/unix-msed/actions/workflows/ci.yml)

The main assignment of a graduate UNIX course (spring 2025), in two parts:

| Part | File | Written in | How it works |
|---|---|---|---|
| 1 | [`part1-csh/msed`](part1-csh/msed) | C shell, **no awk** | translates the program into a plain sed script and runs GNU sed |
| 2 | [`part2-awk/msed`](part2-awk/msed) | GNU awk, **no sed** | parses the program and runs it itself (pattern space, hold space, t flag) |

Both are used the same way:

```sh
cat infile | ./msed '<program>' [arguments...]
```

```console
$ printf 'apple pie\nbanana\ncherry\n' | ./msed 's/apple/$2/;$-1C (gone);1a note\; here' kiwi
kiwi pie
note; here
(gone)
cherry
```

Both versions pass the same 103 hand-checked cases, and a random
differential test runs thousands of generated programs through both and
compares them with GNU sed (see [Testing](#testing)).

> **About the spec.** The original handout and template are lost. The
> language below is rebuilt from my notes on the assignment; where the
> notes do not say, msed does what GNU sed does (for example, `D` on a
> pattern space with no newline acts like `d`). The rules are written out
> in full so the behaviour can be checked against them.

## The language

Everything GNU sed accepts, plus:

| | Meaning |
|---|---|
| `f` | Set the t flag (the next `t` will branch). |
| `F` | Clear the t flag. |
| `Z` | Delete the pattern space up to and including the first newline; if there is no newline, delete all of it. Execution continues with the next command. |
| `W file` | Write the first line of the pattern space to `file`. |
| `C text` | Replace the pattern space with `text` and carry on. Unlike `c`, it does not end the cycle, and in a range every line is replaced. |
| `D` | Delete the first line of the pattern space and restart the cycle without reading new input. With no newline, acts like `d`. |
| `$-N` | Address: the line N lines before the last (`$-1` is the second-to-last line, `$-0` is `$`). |
| `$N` | Replaced by the N-th argument of msed. `$1` is the program itself, so the first extra argument is `$2`. |
| `\$` | A literal `$`: `\$3` stays `$3`. |
| `;` | Separates commands, also after `a i c C w W r R`. |
| `\;` | A literal `;`. |

None of `f Z C` changes the t flag, and `F` changes nothing else.

### Rules in detail

**Splitting on `;`.** msed knows the structure of each command, so a `;`
inside `/regex/`, `s///` or `y///` does not split the program
(`s/a;b/X/` works, as in GNU sed). The commands whose argument normally
runs to the end of the line — `a i c C w W r R` and the `w` flag of `s` —
stop at the first unescaped `;` or newline. Labels stop at `;`, a blank
or `}`.

**Text arguments** (`a i c C`). Leading blanks are dropped. `a\` followed
by a newline is the classic form; `a\  text` keeps the blanks after the
backslash. Inside the text, `\;` is `;`, `\$` is `$`, and the other
escapes mean what they mean in sed (`\t`, `\n`, `\\`, ...). `C text` puts
exactly that text — the same thing `c text` would print — into the
pattern space.

**`$-N`.** The input is counted first. A first (or only) address before
line 1 matches nothing; an end address before line 1 ends the range on
the line where it starts. Inside a regex `$-1` is ordinary text.

**`$N`.** Where an address or a command is expected, the argument is
pasted into the program and read as program text, so `'$2!d' 3` keeps
line 3. Inside a regex, a replacement, a text or a file name the value
also counts as program text (in `s/x/$2/` an `&` in the value still means
the match), but it can never end that field: a `/` in the value is
escaped, and a `;` in the value of `a $2` is just a character. A missing
argument is empty.

## Part 1: translating to sed (C shell)

The script follows the course template's steps: standard input goes to
`t4`, the program to `t5`, and the translated sed script ends up in `t9`,
which `sed -f t9 t4` runs.

A csh variable cannot safely hold quotes, backslashes, `!` or newlines, so
the program is first turned into hex bytes with `od` — one word per byte —
and the translator is a state machine over that word list. It writes the
new script as hex too; `printf` turns it back into bytes at the end.

The new commands become ordinary sed. The only subtle part is the t flag:
`C` and `Z` are substitutions underneath, and a substitution sets the
flag, so they are wrapped in a few branches that put the flag back the
way it was. For `$-1C new text;Z;F` on a 3-line input msed generates:

```sed
2{
t __msed1T
s/.*/new text/
t __msed1F
:__msed1F
b __msed1E
:__msed1T
s/.*/new text/
s/^//
:__msed1E
}
{
t __msed2T
s/^[^\n]*\n\{0,1\}//
t __msed2F
:__msed2F
b __msed2E
:__msed2T
s/^[^\n]*\n\{0,1\}//
s/^//
:__msed2E
}
{
t __msed3F
:__msed3F
}
```

* a `t` to the very next line only clears the flag, which is all `F` needs;
* `f` is `s/^//`, a substitution that always succeeds;
* `W` and `D` exist in GNU sed with the same meaning and are passed through;
* `$-N` becomes a line number, and `$N` is copied in from `argv`.

Runs under both `csh` (bsd-csh) and `tcsh`. Needs GNU sed.

## Part 2: running it in awk

`part2-awk/msed` is a single GNU awk program (`#!/usr/bin/gawk -E`). It
reads the program into a table of commands and runs them: the pattern
space, hold space and t flag are awk variables; `n` and `N` take the next
line with `getline`.

* **Lookahead.** Input is read one line ahead, so `$` is known; for
  `$-N` it reads N+1 lines ahead, and still streams.
* **Regexes.** sed's basic regexes are rewritten as awk regexes
  (`\(` → `(`, a literal `+` → `\+`, `\b` → `\y`, bracket expressions,
  `^`/`$`/`*` that are literal in sed, ...).
* **`s///`.** One `gensub` call marks every match and its groups with
  control characters that are not in the pattern space; the replacement
  is then built per match. This gives the same matches as sed for `g`,
  `N`, `Ng` and empty matches, and makes `\1`–`\9`, `\U \L \u \l \E` work.
* **The details sed users never notice** are copied from GNU sed and
  checked against it: ranges whose commands are skipped by a branch,
  `c` printing only at the end of a range, `a`/`r` output when `n`/`N`
  read a line, a last line with no newline, `q` and `Q`.

Not supported in Part 2: back-references inside a regex (`\(a\)\1`, awk
regexes have none), the `M` flag, `e`. `l` escapes non-ASCII bytes only in
the C locale.

## Testing

```sh
make test          # everything below, about 2 minutes
```

* [`tests/golden.sh`](tests/golden.sh): 103 cases with the expected output
  worked out by hand — every new command and rule above, plus error cases.
  Run against Part 1 under `csh` and under `tcsh`, and against Part 2.
* [`tests/fuzz.py`](tests/fuzz.py): random programs built as a syntax tree
  and printed twice — as an msed program, and as a plain sed script that
  spells out the new commands in a different way from Part 1 (with `T`,
  `z` and its own labels) and resolves `$-N` and `$N` itself. GNU sed runs
  the plain script; Part 1 and Part 2 run the msed program; standard
  output, exit status and files written by `w`/`W` must agree.
  `--std` leaves the new commands out, so both parts are compared directly
  with GNU sed.

CI runs all of it on every push.

## Files

```
part1-csh/msed     Part 1, C shell
part2-awk/msed     Part 2, GNU awk
tests/golden.sh    hand-written cases
tests/fuzz.py      differential tests against GNU sed
Makefile           make test
```
