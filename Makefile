# make test        hand-written cases, then random differential tests
# make golden      only the hand-written cases
# make fuzz        only the random tests (CASES=... SEED=... to change)

CASES ?= 1000
SEED  ?= 1

.PHONY: test golden fuzz

test: golden fuzz

golden:
	tests/golden.sh 'csh -f part1-csh/msed'
	tests/golden.sh 'tcsh -f part1-csh/msed'
	tests/golden.sh part2-awk/msed

fuzz:
	tests/fuzz.py --std --cases $(CASES) --seed $(SEED)
	tests/fuzz.py --cases $(CASES) --seed $(SEED)
