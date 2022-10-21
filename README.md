# Z80Asm - A Z80 Assembler written in Python

An assembler for 8080, Z80 and Z180 opcodes which supports a number of programming styles.
Mostly of interest to Memotech owners.

A usage summary is given below, for more detail see the PDF documentation.

```
usage: Z80Asm [-h] [-v] [-b [BINARY]] [-f FILL] [-x [HEX]] [-y [SYMBOL]] [-n]
              [-l [LIST]] [--list-force] [--list-cond] [-a] [-o [OUTPUT]]
              [-r {MA,M80,ZASM}] [--multi-inc] [-m] [-k [KEEP]] [-e]
              [-t {8080,Z80,Z180}] -s {MA,M80,PASMO,ZASM} [-p]
              [-u [{ALL,ORG,BORG,OFFSET,PHASE,DEPHASE,LOAD}]] [-c CSEG]
              [-d DSEG] [--debug] [-D DEFINE]
              [source ...]

Assemble Z80 code written in different styles

positional arguments:
  source                The Z80 source file(s)

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -b [BINARY], --binary [BINARY]
                        Machine code in binary format
  -f FILL, --fill FILL  Fill byte for undefined addresses
  -x [HEX], --hex [HEX]
                        Machine code in Intel hex format
  -y [SYMBOL], --symbol [SYMBOL]
                        Save all symbol definitions in source format
  -n, --number-build    Append build number to assembled file names
  -l [LIST], --list [LIST]
                        List file
  --list-force          Ignore NOLIST directives
  --list-cond           List false conditional code
  -a, --address         Show load address as well as relocation
  -o [OUTPUT], --output [OUTPUT]
                        Reformatted source file
  -r {MA,M80,ZASM}, --reformat {MA,M80,ZASM}
                        Style for reformatted source (default M80)
  --multi-inc           Include files multiple times in reformatted source
  -m, --modeline        Emacs modeline in reformatted source
  -k [KEEP], --keep [KEEP]
                        Keep pass 1 list file
  -e, --echo            Echo source to screen
  -t {8080,Z80,Z180}, --cpu-type {8080,Z80,Z180}
                        The processor type
  -s {MA,M80,PASMO,ZASM}, --style {MA,M80,PASMO,ZASM}
                        The style of the Z80 source
  -p, --permissive      Ignore some syntax errors
  -u [{ALL,ORG,BORG,OFFSET,PHASE,DEPHASE,LOAD}], --update [{ALL,ORG,BORG,OFFSET,PHASE,DEPHASE,LOAD}]
                        Allow updating (patching) of previous code
  -c CSEG, --cseg CSEG  Start address for code segment
  -d DSEG, --dseg DSEG  Start address for data segment
  --debug               Show assembler debug info
  -D DEFINE, --define DEFINE
                        Define an assembler equate
```
