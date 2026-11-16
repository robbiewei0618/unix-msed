#!/bin/bash
#
# Hand-written cases with the output worked out by hand.
#
#     tests/golden.sh 'csh -f part1-csh/msed'
#     tests/golden.sh 'tcsh -f part1-csh/msed'
#     tests/golden.sh part2-awk/msed
#
# check NAME PROGRAM INPUT EXPECTED [ARGS...]   compares standard output
# file  NAME FILE EXPECTED                      compares a file written by w/W
# status NAME PROGRAM INPUT CODE                compares the exit status
# fails NAME PROGRAM INPUT                      expects an error

set -u
here=$(cd "$(dirname "$0")/.." && pwd)
read -r -a RUN <<< "$1"
# make the implementation path absolute
RUN[-1]=$(cd "$here" && realpath "${RUN[-1]}")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
printf 'R1\nR2\n' > rf
export LC_ALL=C

pass=0
fail=0

report() {
    if [[ "$2" == "$3" ]]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "FAIL: $1"
        echo "  want: $(printf '%q' "$2")"
        echo "  got:  $(printf '%q' "$3")"
    fi
}

check() {
    local name=$1 prog=$2 input=$3 want=$4
    shift 4
    local got
    got=$(printf '%s' "$input" | "${RUN[@]}" "$prog" "$@" 2>&1; echo x)
    report "$name" "$want" "${got%x}"
}

file() {
    local got
    got=$(cat "$2" 2>&1; echo x)
    report "$1" "$3" "${got%x}"
}

status() {
    local name=$1 prog=$2 input=$3 want=$4
    printf '%s' "$input" | "${RUN[@]}" "$prog" > /dev/null 2>&1
    report "$name" "$want" "$?"
}

# an error: any non-zero status, and nothing on standard output
fails() {
    local name=$1 prog=$2 input=$3 out rc
    out=$(printf '%s' "$input" | "${RUN[@]}" "$prog" 2> /dev/null)
    rc=$?
    report "$name" "error, no output" "$([[ $rc -ne 0 && -z $out ]] && echo 'error, no output' || echo "status $rc, output $out")"
}

I5=$'one\ntwo\nthree\nfour\nfive\n'
N4=$'1\n2\n3\n4\n'

# ------------------------------------------------------------- f and F
check "f sets the flag"           'f;t x;s/^/NO /;:x'        $'a\n'      $'a\n'
check "no f, no jump"             't x;s/^/NO /;:x'          $'a\n'      $'NO a\n'
check "F clears a substitution"   's/a/A/;F;t x;s/$/ !/;:x'  $'a\nb\n'   $'A !\nb !\n'
check "same without F"            's/a/A/;t x;s/$/ !/;:x'    $'a\nb\n'   $'A\nb !\n'
check "f then F"                  'f;F;t x;s/^/-/;:x'        $'a\n'      $'-a\n'
check "F then f"                  'F;f;t x;s/^/-/;:x'        $'a\n'      $'a\n'
check "F with an address"         's/./X/;2F;t x;s/$/!/;:x'  $'a\nb\nc\n' $'X\nX!\nX\n'
check "f with an address"         '/b/f;t x;s/$/!/;:x'       $'a\nb\n'   $'a!\nb\n'
check "several F"                 'F;F;s/a/A/;F;t x;s/$/!/;:x' $'a\n'    $'A!\n'
check "F with !"                  's/./X/;2!F;t x;s/$/!/;:x' $'a\nb\nc\n' $'X!\nX\nX!\n'

# ------------------------------------------------------------------- Z
check "Z drops the first line"    'N;Z'                      "$N4"       $'2\n4\n'
check "Z without newline"         'Z'                        $'a\nb\n'   $'\n\n'
check "Z keeps the flag"          's/x/X/;Z;t y;s/^/no/;:y'  $'x\na\n'   $'\nno\n'
check "Z does not end the cycle"  'N;N;Z;s/^/>/'             $'1\n2\n3\n' $'>2\n3\n'
check "Z with an address"         '2Z'                       $'a\nb\nc\n' $'a\n\nc\n'
check "Z twice"                   'N;N;Z;Z'                  $'1\n2\n3\n' $'3\n'

# ------------------------------------------------------------------- W
check "W writes the first line"   'N;W out'                  "$N4"       "$N4"
file  "W file"                    out                        $'1\n3\n'
check "W name ends at ;"          'W out2;s/^/x/'            $'a\nb\n'   $'xa\nxb\n'
file  "W file 2"                  out2                       $'a\nb\n'
check "W name with \\;"           'W a\;b'                   $'q\n'      $'q\n'
file  "W file a;b"                'a;b'                      $'q\n'
check "W with an address"         '$!N;2W out3;P;D'          $'a\nb\nc\n' $'a\nb\nc\n'
file  "W file 3"                  out3                       $'a\n'

# ------------------------------------------------------------------- C
check "C replaces a line"         '2C new'                   "$I5"       $'one\nnew\nthree\nfour\nfive\n'
check "C keeps going"             'C X;s/X/Y/'               $'a\n'      $'Y\n'
check "c stops (compare)"         'c X;s/X/Y/'               $'a\n'      $'X\n'
check "C in a range"              '2,3C -'                   "$I5"       $'one\n-\n-\nfour\nfive\n'
check "c in a range (compare)"    '2,3c -'                   "$I5"       $'one\n-\nfour\nfive\n'
check "C on two lines"            'N;C joined'               "$N4"       $'joined\njoined\n'
check "C keeps the flag"          's/a/A/;C z;t y;s/^/no/;:y' $'a\nb\n'  $'z\nnoz\n'
check "C special characters"      'C a&b/c\\d'               $'x\n'      $'a&b/c\\d\n'
check "C with \\;"                'C a\;b;s/;/:/'            $'x\n'      $'a:b\n'
check "C with \\n"                'C x\ny;s/\n/+/'           $'q\n'      $'x+y\n'
check "C empty"                   'C;s/^$/E/'                $'q\n'      $'E\n'
check "C with an argument"        'C $2'                     $'q\n'      $'v&1/2\n'   'v&1/2'
check "C leading blanks dropped"  'C    pad'                 $'q\n'      $'pad\n'
check "C\\ keeps blanks"          'C\   pad'                 $'q\n'      $'   pad\n'
check "C with \\1"                'C \1x'                    $'q\n'      $'1x\n'

# ------------------------------------------------------------------- D
check "D: \$!N;P;D"               '$!N;P;D'                  "$I5"       "$I5"
check "D: N;P;D"                  'N;P;D'                    $'1\n2\n3\n' $'1\n2\n3\n'
check "D without newline is d"    'D;s/^/x/'                 $'a\nb\n'   ''
check "D does not read a line"    '$!N;=;P;D'                $'a\nb\nc\n' $'2\na\n3\nb\n3\nc\n'
check "D restarts, no new line"   '1{N;N};s/^/>/;/\n/D'      $'1\n2\n3\n' $'>3\n'

# ----------------------------------------------------------------- $-N
check "\$-1"                      '$-1!d'                    "$I5"       $'four\n'
check "\$-2"                      '$-2!d'                    "$I5"       $'three\n'
check "\$-1,\$"                   '$-1,$!d'                  "$I5"       $'four\nfive\n'
check "2,\$-2"                    '2,$-2!d'                  "$I5"       $'two\nthree\n'
check "\$-4 is line 1"            '$-4!d'                    "$I5"       $'one\n'
check "\$-5 is no line"           '$-5!d'                    "$I5"       ''
check "\$-9 is no line"           '$-9!d'                    "$I5"       ''
check "\$-0 is \$"                '$-0!d'                    "$I5"       $'five\n'
check "end before start"          '4,$-3!d'                  "$I5"       $'four\n'
check "end before line 1"         '2,$-9!d'                  "$I5"       $'two\n'
check "\$-1 of one line"          '$-1!d'                    $'x\n'      ''
check "\$-1 of no input"          '$-1p'                     ''          ''
check "\$-10"                     '$-10!d'                   "$(seq 12)"$'\n' $'2\n'
check "/re/,\$-1"                 '/three/,$-1d'             "$I5"       $'one\ntwo\nfive\n'
check "\$-1i"                     '$-1i X'                   "$I5"       $'one\ntwo\nthree\nX\nfour\nfive\n'
check "\$-2,\$-1 block"           '$-2,$-1{s/^/>/}'          "$I5"       $'one\ntwo\n>three\n>four\nfive\n'
check "\$-1 in a regex is text"   's/$-1/X/'                 $'a$-1\n'   $'aX\n'
check "\$-1 with no newline"      '$-1s/^/>/'                $'a\nb\nc'  $'a\n>b\nc'

# ------------------------------------------------------------------ $N
check "\$2 in s"                  's/apple/$2/g'             $'apple pie apple\n' $'banana pie banana\n' banana
check "\$2\$3"                    's/x/$2$3/'                $'x\n'      $'AB\n'      A B
check "\$2 as an address"         '$2!d'                     "$I5"       $'two\n'     2
check "\$2,\$3"                   '$2,$3!d'                  "$I5"       $'two\nthree\nfour\n' 2 4
check "\$2 in a regex"            '/$2/d'                    "$I5"       $'one\nfour\nfive\n' t
check "missing argument"          's/o/[$5]/'                $'one\n'    $'[]ne\n'
check "\\\$2 is literal"          's/x/\$2/'                 $'x\n'      $'$2\n'      ignored
check "\\\$2 in a regex"          's/\$2/Y/'                 $'a$2\n'    $'aY\n'      ignored
check "\\\$3 in text"             'a cost \$3'               $'x\n'      $'x\ncost $3\n'
check "\$2 in text"               'a $2'                     $'x\n'      $'x\nhello world\n' 'hello world'
check "value with /"              's/x/$2/'                  $'x\n'      $'a/b\n'     a/b
check "value with ;"              'a $2'                     $'x\n'      $'x\np;q\n'  'p;q'
check "value with &"              's/x/[$2]/'                $'x\n'      $'[xx]\n'    '&&'
check "\$2 as a command"          '$2'                       $'x\n'      $'x\nx\n'    p
check "\$2 in a file name"        'w $2'                     $'x\n'      $'x\n'       wout
file  "w \$2 file"                wout                       $'x\n'

# ----------------------------------------------------------- ; and \;
check "two s"                     's/a/b/;s/b/c/'            $'a\n'      $'c\n'
check "a then d"                  '1a x;2d'                  "$I5"       $'one\nx\nthree\nfour\nfive\n'
check "a with \\;"                'a x\;y'                   $'q\n'      $'q\nx;y\n'
check "i with a newline"          $'1i\\\nhello'             $'q\n'      $'hello\nq\n'
check "a and i"                   '$a end;1i start'          $'q\n'      $'start\nq\nend\n'
check "r then a command"          '2r rf;2s/^/>/'            "$I5"       $'one\n>two\nR1\nR2\nthree\nfour\nfive\n'
check "w then a command"          'w wf;s/o/0/g'             $'foo\n'    $'f00\n'
file  "w file"                    wf                         $'foo\n'
check "c ends at ;"               'c X;p'                    $'q\n'      $'X\n'
check "y then s"                  'y/abc/xyz/;s/x/X/'        $'abc\n'    $'Xyz\n'
check "; inside s"                's/a;b/X/'                 $'a;b\n'    $'X\n'
check "\\; inside s"              's/a\;b/X/'                $'a;b\n'    $'X\n'
check "; as delimiter"            's;a;b;'                   $'a\n'      $'b\n'
check "escaped ; delimiter"       's;a\;b;X;'                $'a;b\n'    $'X\n'
check "labels and ;"              ':a;N;$!ba;s/\n/,/g'       "$I5"       $'one,two,three,four,five\n'
check "braces"                    '/two/{s/t/T/;p}'          $'one\ntwo\n' $'one\nTwo\nTwo\n'
check "comment"                   'p # print twice'          $'a\n'      $'a\na\n'
check "#n"                        $'#n\n2p'                  "$I5"       $'two\n'
check "a then }"                  '/x/{a A;}'                $'x\ny\n'   $'x\nA\ny\n'

# ------------------------------------------------------------- errors
fails  "unterminated s"           's/a/b'                    $'a\n'
fails  "unknown command"          'k'                        $'a\n'
fails  "extra characters"         'p x'                      $'a\n'
fails  "unmatched {"              '{p'                       $'a\n'
fails  "missing label"            'b nowhere'                $'a\n'
status "q exit code"              'q5'                       $'a\n'      5

echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
