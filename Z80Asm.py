#!/usr/bin/python3
#
# Program to assemble Z80 mnenonics supporting either traditional or MA style formatting.
#
# License: BSD-2-Clause
#
import sys
import os
import time
import struct
import glob
import argparse
#
# Convert a string to Integer, accepting different bases
def IntVal (s):
    try:
        return int (s, 0)
    except ValueError as e:
        raise argparse.ArgumentTypeError (str(e))
#
# Find first of specified characters in line (outside quotes) and return position or -1 if not found
def FindChar (sLine, lFind):
    quote = None
    for iCh, ch in enumerate (sLine):
        if ( ( ch == '"' ) or ( ch == "'" ) ):
            if ( quote is None ):
                quote = ch
            elif ( quote == ch ):
                quote = None
        elif ( ( ch in lFind ) and ( quote is None ) ):
            return iCh
    return -1
#
def CountFields (sLine, lSep):
    quote = None
    bSep = True
    nField = 0
    for ch in sLine:
        if ( ( quote is None ) and ( ch in lSep ) ):
            bSep = True
        else:
            if ( bSep ):
                nField += 1
                bSep = False
            if ( ( ch == '"' ) or ( ch == "'" ) ):
                if ( quote is None ):
                    quote = ch
                elif ( quote == ch ):
                    quote = None
    return nField
#
def TriArg (tf, a, b):
    if ( tf ):
        return a
    return b
#
def HexFmt (v, d):
    if ( v < 0 ):
        return '-' + HexFmt (-v, d)
    sFmt = '0x{:0' + '{:d}'.format (d) + 'X}'
    return sFmt.format (v)
#
# A class for storing label definitions
class Label:
    def __init__ (self, name, seg, value, location):
        self.name = name
        self.seg = seg
        self.value = value
        self.file = location[0]
        self.line = location[1]
#
# Generate Intel Hex format file
class HexOut:
    def __init__ (self, sFile):
        self.sFile = sFile
        self.f = open (sFile, 'w')
        self.addr = None
        self.data = bytearray ()
#
    def Write (self):
        if ( ( self.addr is not None ) and ( self.data ) ):
            n = len (self.data)
            cs = n + (self.addr >> 8) + (self.addr & 0xFF)
            sHex = ':{:02X}{:04X}00'.format (n, self.addr)
            for by in self.data:
                cs += by
                sHex += '{:02X}'.format (by)
            cs = 0x100 - ( cs & 0xFF )
            sHex += '{:02X}\n'.format (cs)
            self.f.write (sHex)
            self.addr += n
            self.data = bytearray ()
#
    def SetAddr (self, addr, bInit = True):
        if ( self.addr is None ):
            if ( bInit ):
                self.addr = addr
        else:
            if ( self.addr + len (self.data) != addr ):
                self.Write ()
            self.addr = addr
#
    def Data (self, ba):
        if ( self.addr is not None ):
            for by in ba:
                self.data.append (by)
                if ( len (self.data) >= 16 ):
                    self.Write ()
#
    def Close (self, addr, bKill = False):
        self.Write ()
        cs = 0x100 - ( ( (addr >> 8) + (addr & 0xFF) + 1 ) & 0xFF )
        sHex = ':00{:04X}01{:02X}\n'.format (addr, cs)
        self.f.write (sHex)
        self.f.close ()
        if ( bKill ):
            os.remove (self.sFile)
#
# Generate binary output
class BinOut:
    def __init__ (self, sFile, byFill):
        self.sFile = sFile
        self.f = open (sFile, 'wb')
        self.base = None
        self.data = bytearray ()
        self.fill = bytes ((byFill,))
        self.addr = 0
        self.maxaddr = 0
#
    def SetFill (self, byFill):
        self.fill = bytes ((byFill,))
#
    def Write (self):
        if ( ( self.base is not None ) and ( self.data ) ):
            self.f.write (self.data)
        self.data = bytearray ()
#
    def SetAddr (self, addr, bInit = True):
        if ( self.base is None ):
            if ( bInit ):
                self.base = addr
                self.addr = addr
                self.maxaddr = addr
        elif ( addr > self.maxaddr ):
            self.Write ()
            if ( self.addr < self.maxaddr ):
                self.f.seek (self.maxaddr - self.base)
            self.f.write (self.fill * ( addr - self.maxaddr ))
            self.addr = addr
            self.maxaddr = addr
        elif ( addr != self.addr ):
            self.Write ()
            self.f.seek (addr - self.base)
            self.addr = addr
#
    def Data (self, ba):
        if ( self.base is not None ):
            for by in ba:
                self.data.append (by)
                if ( len (self.data) >= 256 ):
                    self.Write ()
            self.addr += len (ba)
            if ( self.addr > self.maxaddr ):
                self.maxaddr = self.addr
#
    def Close (self, bKill = False):
        self.Write ()
        self.f.close ()
        if ( bKill ):
            os.remove (self.sFile)
#
class Reformat:
    def __init__ (self, parent, styOut, bMulti):
        self.parent = parent
        self.styOut = styOut
        self.bMulti = bMulti
        self.bStrict = parent.bStrict
        self.fOut = None
        self.bHold = False
        self.Reset ()
        self.list = [True]
        self.include = set ()
#
    def Reset (self):
        self.sOpCode = None
        self.labels = []
        self.args = []
        self.sCmnt = None
#
    def StartInclude (self, sInclude):
        if ( ( self.fOut ) and ( not self.bMulti ) ):
            inc = self.list[-1]
            if ( inc ):
                inc = sInclude not in self.include
                if ( inc ):
                    self.include.add (sInclude)
            self.list.append (inc)
#
    def EndInclude (self):
        if ( ( self.fOut ) and ( not self.bMulti ) ):
            self.list.pop ()
            self.Reset ()
#
    def Debug (self, sMsg):
        if ( self.fOut ):
            self.fOut.write (sMsg + '\n')
#
    def Open (self, sFile):
        self.sFile = sFile
        self.fOut = open (sFile, 'w')
#
    def Close (self, bKill = False):
        self.OpCode ('END')
        self.Output ()
        self.fOut.close ()
        self.fOut = None
        if ( bKill ):
            os.remove (self.sFile)
#
    def Label (self, sLabel):
        if ( self.bHold ):
            self.bHold = False
            # self.Debug ('Prior to Label ' + sLabel)
            self.Output ()
        self.labels.append (sLabel)
        # self.Debug ('Add label: ' + sLabel)
#
    def OpCode (self, sOpCode):
        if ( self.bHold ):
            self.bHold = False
            # self.Debug ('Prior to OpCode ' + sOpCode)
            self.Output ()
        self.sOpCode = sOpCode
#
    def AddArg (self, arg):
        self.args.append (arg)
#
    def Comment (self, sCmnt):
        self.sCmnt = sCmnt
#
    def CmntLine (self, sCmnt):
        if ( ( self.list[-1] ) and ( self.fOut ) ):
            self.fOut.write (sCmnt + '\n')
#
    def TabTo (self, nTab, bWrap = False):
        nPos = 0
        for ch in self.sLine:
            if ( ch == '\n' ):
                nPos = 0
            elif ( ch == '\t' ):
                nPos = 8 * ( nPos // 8 + 1 )
            else:
                nPos += 1
        if ( bWrap and ( nPos >= nTab ) ):
            self.sLine += '\n'
            nPos = 0
        while ( nPos < nTab ):
            self.sLine += '\t'
            nPos += 8
#
    def Expression (self, lExpr):
        nTerm = len (lExpr)
        for t in lExpr:
            term = t[0]
            arg = t[-1]
            if ( term == ',' ):
                break
            elif ( term == 'B' ):
                if ( ( arg >= 0 ) and ( arg < 256 ) ):
                    if ( self.styOut == 'MA' ):
                        self.sLine += '%{:08b}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        self.sLine += '{:08b}B'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:02X}'.format (arg)
                else:
                    if ( self.styOut == 'MA' ):
                        self.sLine += '%{:016b}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        self.sLine += '{:b}016B'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:04X}'.format (arg)
            elif ( term == 'D' ):
                self.sLine += '{:d}'.format (arg)
            elif ( term == 'H' ):
                if ( ( arg >= 0 ) and ( arg < 256 ) ):
                    if ( self.styOut == 'MA' ):
                        self.sLine += '&{:02X}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        if ( arg < 160 ):
                            self.sLine += '{:02X}H'.format (arg)
                        else:
                            self.sLine += '{:03X}H'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:02X}'.format (arg)
                else:
                    if ( self.styOut == 'MA' ):
                        self.sLine += '&{:04X}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        if ( arg < 40960 ):
                            self.sLine += '{:04X}H'.format (arg)
                        else:
                            self.sLine += '{:05X}H'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:04X}'.format (arg)
            elif ( term == 'Q' ):
                if ( ( arg >= 0 ) and ( arg < 256 ) ):
                    if ( self.styOut == 'MA' ):
                        self.sLine += '&{:02X}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        self.sLine += '{:03o}Q'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:02X}'.format (arg)
                else:
                    if ( self.styOut == 'MA' ):
                        self.sLine += '&{:04X}'.format (arg)
                    elif ( self.styOut == 'M80' ):
                        self.sLine += '{:06o}Q'.format (arg)
                    elif ( self.styOut == 'ZASM' ):
                        self.sLine += '#{:04X}'.format (arg)
            elif ( term == '"' ):
                if ( ( self.styOut == 'MA' ) and  ( nTerm != 2 ) ):
                        self.sLine += '+ASC"{:s}"'.format (arg)
                else:
                    self.sLine += '"{:s}"'.format (arg)
            elif ( term == 'L' ):
                if ( self.parent.bLabCase ):
                    self.sLine += arg
                else:
                    lab = arg.lower ()
                    if ( lab in self.parent.publics ):
                        self.sLine += self.parent.publics[lab].name
                    elif ( lab in self.parent.labels ):
                        self.sLine += self.parent.labels[lab].name
                    else:
                        self.sLine += arg
            elif ( term in '+-*/()' ):
                self.sLine += term
            elif ( term in ['U+', 'U-'] ):
                self.sLine += term[1]
            elif ( term in ['U~', 'NOT'] ):
                if ( self.styOut == 'M80' ):
                    self.sLine += 'NOT '
                else:
                    self.sLine += '~'
            elif ( term in ['&', 'AND'] ):
                if ( self.styOut == 'M80' ):
                    self.sLine += ' AND '
                else:
                    self.sLine += '&'
            elif ( term in ['!', 'OR'] ):
                if ( self.styOut == 'M80' ):
                    self.sLine += ' OR '
                else:
                    self.sLine += '!'
            elif ( term in ['^', 'XOR'] ):
                if ( self.styOut == 'M80' ):
                    self.sLine += ' XOR '
                else:
                    self.sLine += '^'
            else:
                self.sLine += ' ' + term + ' '
#
#   Set load address and origin
#       Code    MA              M80             ZASM
#       A       BORG xxxx
#       B       ORG xxxx        ORG xxxx        LOAD xxxx
#       O       OFFSET xxxx     .PHASE xxxx     ORG xxxx
#       R       OFFSET          .DEPHASE        ORG
    def Position (self, type, offset = 0):
        # self.Debug ('Position ({:s}, {:04X})'.format (type, offset))
        if ( type == 'R' ):
            self.args = []
            if ( self.styOut == 'MA' ):
                self.sOpCode = 'OFFSET'
            elif ( self.styOut == 'M80' ):
                self.sOpCode = '.DEPHASE'
            elif ( self.styOut == 'ZASM' ):
                self.sOpCode = 'ORG'
            self.bHold = False
            # self.Debug ('Type R Output')
            self.Output ()
            return
        elif ( type == 'A' ):
            if ( self.styOut == 'MA' ):
                self.Output ();
                return
            if ( offset != 0 ):
                arg = self.args[-1]
                lOrg = [('H', -offset), ('+',)]
                lOrg.extend (arg)
                self.args = [lOrg]
            if ( self.styOut == 'ZASM' ):
                self.sOpCode = 'LOAD'
            else:
                self.sOpCode = 'ORG'
            # self.Debug ('Type A Output')
            self.bHold = False
            self.Output ()
            if ( offset != 0 ):
                if ( self.styOut == 'ZASM' ):
                    self.sOpCode = 'ORG'
                else:
                    self.sOpCode = '.PHASE'
                self.args = [arg]
                self.Output ()
            return
        elif ( type == 'B' ):
            arg = self.args[-1]
            self.args = [arg]
            if ( self.styOut == 'ZASM' ):
                self.sOpCode = 'LOAD'
            else:
                self.sOpCode = 'ORG'
            # self.Debug ('Type B Output')
            self.bHold = False
            self.Output ()
            if ( offset != 0 ):
                lOrg = [('H', offset), ('+',)]
                lOrg.extend (arg)
                self.args = [lOrg]
                # self.args = [[arg[0], ('+',), ('H', offset), (',',)]]
            elif ( self.styOut == 'ZASM' ):
                self.args = [arg]
            else:
                return
            self.bHold = True
        if ( self.styOut == 'MA' ):
            self.sOpCode = 'OFFSET'
        elif ( self.styOut == 'M80' ):
            self.sOpCode = '.PHASE'
        elif ( self.styOut == 'ZASM' ):
            self.sOpCode = 'ORG'
        if ( type == 'O' ):
            if ( self.args ):
                self.args = [self.args[-1]]
            # self.Debug ('Type O Output')
            self.bHold = False
            self.Output ()
#
    def StringCode (self, sOp):
        lTerm = []
        for arg in self.args:
            if ( ( len (arg) == 2 ) and ( arg[0][0] == '"' ) ):
                sTerm = arg[0][1]
                while (True):
                    nCh = sTerm.find ('\\')
                    if ( nCh < 0 ):
                        break
                    while ( sTerm[nCh+1] == '\\' ):
                        nCh = sTerm.find ('\\', nCh+2)
                    if ( nCh < 0 ):
                        break
                    if ( nCh > 0 ):
                        lTerm.append (('S', [('"', sTerm), (',',)]))
                    try:
                        iVal = int (sTerm[nCh+1:nCh+3], 16)
                    except ValueError:
                        iVal = 0
                    if ( ( sOp == 'C' ) and ( nCh + 3 == len (sTerm) ) ):
                        iVal |= 0x80
                    lTerm.append (('B', [('H', iVal), (',',)]))
                    sTerm = sTerm[nCh+3:]
                if ( sTerm ):
                    lTerm.append ((sOp, [('"', sTerm), (',',)]))
            else:
                lTerm.append (('B', arg))
        sOp = None
        for term in lTerm:
            if ( term[0] != sOp ):
                if ( sOp is not None ):
                    self.Output ()
                sOp = term[0]
                self.sOpCode = 'DEF' + sOp
                self.args = []
            self.args.append (term[1])
        self.Output ()
#
    def Output (self):
        if ( ( self.list[-1] ) and ( not self.bHold ) and ( self.sOpCode ) ):
            if ( self.fOut ):
                # self.Debug (str (self.labels))
                if ( self.sOpCode in ['DB', 'DEFB'] ):
                    if ( self.styOut == 'ZASM' ):
                        self.sOpCode = 'DEFB'
                    else:
                        self.sOpCode = 'DB'
                elif ( self.sOpCode in ['DW', 'DEFW'] ):
                    if ( self.styOut == 'ZASM' ):
                        self.sOpCode = 'DEFW'
                    else:
                        self.sOpCode = 'DW'
                elif ( self.sOpCode in ['DD', 'DEFD'] ):
                    if ( self.styOut == 'ZASM' ):
                        self.sOpCode = 'DEFD'
                    else:
                        self.sOpCode = 'DD'
                elif ( self.sOpCode in ['DS', 'DEFS'] ):
                    if ( self.styOut == 'ZASM' ):
                        self.sOpCode = 'DEFS'
                    elif ( self.styOut == 'M80' ):
                        self.sOpCode = 'DB'
                    else:
                        self.sOpCode = 'DS'
                elif ( self.sOpCode in ['DC', 'DEFC'] ):
                    if ( self.styOut == 'ZASM' ):
                        self.sOpCode = 'DEFC'
                    else:
                        self.sOpCode = 'DC'
                elif ( self.sOpCode == 'BYTE' ):
                    if ( self.styOut == 'M80' ):
                        self.sOpCode = 'DS'
                elif ( self.sOpCode == 'WORD' ):
                    if ( self.styOut == 'M80' ):
                        self.sOpCode = 'DS'
                        lExpr = [('D', 2), ('*',)]
                        lExpr.extend (self.args[0])
                        self.args[0] = lExpr
                if ( self.sOpCode in ['LIST', '.LIST'] ):
                    if ( self.styOut == 'M80' ):
                        self.sOpCode = '.LIST'
                    else:
                        self.sOpCode = 'LIST'
                if ( self.sOpCode in ['NOLIST', '.XLIST'] ):
                    if ( self.styOut == 'M80' ):
                        self.sOpCode = '.XLIST'
                    else:
                        self.sOpCode = 'NOLIST'
                self.sLine = ''
                nTab = 0
                if ( self.styOut == 'MA' ):
                    if ( self.sOpCode == 'EQU' ):
                        for sLabel in self.labels[0:-1]:
                            self.fOut.write ('.' + sLabel + '\n')
                        self.sLine = self.labels[-1] + '\t'
                        nTab = 16
                        self.TabTo (nTab)
                    else:
                        for sLabel in self.labels:
                            self.fOut.write ('.' + sLabel + '\n')
                else:
                    if ( self.labels ):
                        for sLabel in self.labels[0:-1]:
                            self.fOut.write (sLabel + ':\n')
                        self.sLine = self.labels[-1]
                        if ( ( self.styOut == 'M80' ) and ( self.sOpCode == 'EQU' ) ):
                            self.sLine += '\t'
                        else:
                            self.sLine += ':\t'
                    nTab = 16
                    self.TabTo (nTab)
                if ( self.sOpCode == 'INCLUDE' ):
                    self.sLine = self.sLine.strip ()
                    if ( self.sLine ):
                        self.fOut.write (self.sLine + '\n')
                    self.sLine = ';\t\t'
                self.sLine += self.sOpCode
                nTab += 8
                if ( self.args ):
                    self.sLine += '\t'
                    self.TabTo (nTab)
                bIndex = False
                for iArg, arg in enumerate (self.args):
                    if ( ( iArg > 0 ) and ( not bIndex ) ):
                        self.sLine += ', '
                    if ( isinstance (arg, list) ):
                        self.Expression (arg)
                        if ( bIndex ):
                            self.sLine += ')'
                            bIndex = False
                    else:
                        bIndex = False
                        self.sLine += arg
                        if ( arg in ['(', '(IX', '(IY'] ):
                            bIndex = True
                if ( self.sCmnt ):
                    nTab += 24
                    self.TabTo (nTab, True)
                    self.sLine += self.sCmnt
                self.fOut.write (self.sLine + '\n')
            self.Reset ()
#
class Assembler:
    chLabel = '_$.?@'
    reg8 = {
        'A': 7,
        'B': 0,
        'C': 1,
        'D': 2,
        'E': 3,
        'H': 4,
        'L': 5}
    reg8X = {
        'A': 7,
        'B': 0,
        'C': 1,
        'D': 2,
        'E': 3,
        'H': 4,
        'L': 5,
        '(HL)': 6}
    reg8M = {
        'A': 7,
        'B': 0,
        'C': 1,
        'D': 2,
        'E': 3,
        'H': 4,
        'L': 5,
        'M': 6}
    reg8F = {
        'A': 7,
        'B': 0,
        'C': 1,
        'D': 2,
        'E': 3,
        'H': 4,
        'L': 5,
        'F': 6}
    reg16 = {
        'BC': 0x00,
        'DE': 0x10,
        'HL': 0x20,
        'SP': 0x30}
    reg16O = {
        'B': 0x00,
        'D': 0x10,
        'H': 0x20,
        'SP': 0x30}
    reg16X = {
        'B': 0x00,
        'D': 0x10}
    reg16P = {
        'BC': 0x00,
        'DE': 0x10,
        'HL': 0x20,
        'AF': 0x30}
    reg16Q = {
        'B': 0x00,
        'D': 0x10,
        'H': 0x20,
        'PSW': 0x30}
    regI = {
        'IX': 0xDD,
        'IY': 0xFD}
    cond = {
        'NZ': 0x00,
        'Z':  0x08,
        'NC': 0x10,
        'C':  0x18,
        'PO': 0x20,
        'PE': 0x28,
        'P':  0x30,
        'M':  0x38,
        'HS': 0x10,     # MA special condition codes: HS = C
        'LO': 0x18,     #                             LO = NC
        'MI': 0x38}     #                      Minus: MI = M
    op0 = {
        'CCF': b'\x3F',
        'CPD': b'\xED\xA9',
        'CPDR': b'\xED\xB9',
        'CPI': b'\xED\xA1',
        'CPIR': b'\xED\xB1',
        'CPL': b'\x2F',
        'DAA': b'\x27',
        'DI': b'\xF3',
        'EI': b'\xFB',
        'EXX': b'\xD9',
        'HALT': b'\x76',
        'IND': b'\xED\xAA',
        'INDR': b'\xED\xBA',
        'INI': b'\xED\xA2',
        'INIR': b'\xED\xB2',
        'LDD': b'\xED\xA8',
        'LDDR': b'\xED\xB8',
        'LDI': b'\xED\xA0',
        'LDIR': b'\xED\xB0',
        'NEG': b'\xED\x44',
        'NOP': b'\00',
        'OUTD': b'\xED\xAB',
        'OTDR': b'\xED\xBB',
        'OUTI': b'\xED\xA3',
        'OTIR': b'\xED\xB3',
        'RETI': b'\xED\x4D',
        'RETN': b'\xED45',
        'RLA': b'\x17',
        'RLCA': b'\x07',
        'RLD': b'\xED\x6F',
        'RRA': b'\x1F',
        'RRCA': b'\x0F',
        'RRD': b'\xED\x67',
        'SCF': b'\x37'}
    opA1 = {
        'AND': 0xA0,
        'CP': 0xB8,
        'CMP': 0xB8,    # Work around an MA typo
        'OR': 0xB0,
        'SUB': 0x90,
        'XOR': 0xA8}
    opA2 = {
        'ADC': 0x88,
        'ADD': 0x80,
        'SBC': 0x98}
    opB2 = {
        'BIT': 0x40,
        'RES': 0x80,
        'SET': 0xC0}
    opC = {
        'CALL': (0xCD, 0xC4),
        'JP': (0xC3, 0xC2),
        'JR': (0x18, 0x20)}
    opD = {
        'DEC': (0x05, 0x0B),
        'INC': (0x04, 0x03)}
    opP = {
        'POP': 0xC1,
        'PUSH': 0xC5}
    opR = {
        'RL': 0x10,
        'RLC': 0x00,
        'RR': 0x18,
        'RRC': 0x08,
        'SLA': 0x20,
        'SRA': 0x28,
        'SRL': 0x38}
    op180 = {
        'SLP': 0x76,
        'OTIM': 0x83,
        'OTIMR': 0x93,
        'OTDM': 0x8B,
        'OTDMR': 0x9B}
    op8080A = {
        'ADD': 0x80,
        'ADC': 0x88,
        'SUB': 0x90,
        'SBB': 0x98,
        'ANA': 0xA0,
        'XRA': 0xA8,
        'ORA': 0xB0,
        'CMP': 0xB8}
    op8080X = {
        'ADI': 0xC6,
        'ACI': 0xCE,
        'SUI': 0xD6,
        'SBI': 0xDE,
        'ANI': 0xE6,
        'XRI': 0xEE,
        'ORI': 0xF6,
        'CPI': 0xFE,
        'IN': 0xDB,
        'OUT': 0xD3}
    op8080D = {
        'DAD': 0x09,
        'INX': 0x03,
        'DCX': 0x0B}
    op8080I = {
        'INR': 0x04,
        'DCR': 0x05}
    op8080Z = {
        'XTHL': 0xE3,
        'SPHL': 0xF9,
        'PCHL': 0xE9,
        'XCHG': 0xEB,
        'CMC': 0x3F,
        'STC': 0x37,
        'CMA': 0x2F,
        'DAA': 0x27,
        'HLT': 0x76,
        'NOP': 0x00,
        'DI': 0xF3,
        'EI': 0xFB,
        'RET': 0xC9,
        'RNZ': 0xC0,
        'RZ': 0xC8,
        'RNC': 0xD0,
        'RC': 0xD8,
        'RPO': 0xE0,
        'RPE': 0xE8,
        'RP': 0xF0,
        'RM': 0xF8,
        'RAL': 0x17,
        'RAR': 0x1F,
        'RLC': 0x07,
        'RRC': 0x0F}
    op8080C = {
        'CALL': 0xCD,
        'CNZ': 0xC4,
        'CZ': 0xCC,
        'CNC': 0xD4,
        'CC': 0xDC,
        'CPO': 0xE4,
        'CPE': 0xEC,
        'CP': 0xF4,
        'CM': 0xFC,
        'JMP': 0xC3,
        'JNZ': 0xC2,
        'JZ': 0xCA,
        'JNC': 0xD2,
        'JC': 0xDA,
        'JPO': 0xE2,
        'JPE': 0xEA,
        'JP': 0xF2,
        'JM': 0xFA,
        'SHLD': 0x22,
        'LHLD': 0x2A}
    regLA = {
        '(BC)': (b'\x0A', b'\x02'),
        '(DE)': (b'\x1A', b'\x12'),
        'I': (b'\xED\x57', b'\xED\x47'),
        'R': (b'\xED\x5F', b'\xED\x4F')}
    evLvl = [{          # Normal binding rules
        'U+':9,
        'U-':9,
        'U~':9,         # Bitwise NOT
        'L2':9,         # Number of highest set bit
        'LOW':8,
        'HIGH':8,
        '*':7,
        '/':7,
        'MOD':7,
        'SHL':7,
        'SHR':7,
        '+':6,
        '-':6,
        'EQ':5,
        'NE':5,
        'LT':5,
        'LE':5,
        'GE':5,
        'GT':5,
        'NOT':4,        # Bitwise NOT
        '&':3,          # AND
        'AND':3,
        '!':2,          # OR
        'OR':2,
        '^':2,          # XOR
        'XOR':2,
        '(':1,
        ')':1,
        ',':0},
        {               # Binding rules for MA simple evaluator
        'U+':3,
        'U-':3,
        'U~':3,         # Bitwise NOT
        'L2':3,         # Number of highest set bit
        'LOW':2,
        'HIGH':2,
        '*':2,
        '/':2,
        'MOD':2,
        'SHL':2,
        'SHR':2,
        '+':2,
        '-':2,
        'EQ':2,
        'NE':2,
        'LT':2,
        'LE':2,
        'GE':2,
        'GT':2,
        'NOT':2,        # Bitwise NOT
        '&':2,          # AND
        'AND':2,
        '!':2,          # OR
        'OR':2,
        '^':2,          # XOR
        'XOR':2,
        '(':1,
        ')':1,
        ',':0}]
#
    exStart = 1
    exValue = 2
    exASCII = 3
    exNumber = 4
    exBinary = 5
    exDecimal = 6
    exHex = 7
    exLabel = 8
    exOperator = 9
    exOpWord = 10
#
    def AsmErr (self, sErr):
        if ( self.sErr is None ):
            self.sErr = sErr
#
    def Public (self, sLabel):
        sName = sLabel
        if ( not self.bLabCase ):
            sLabel = sLabel.lower ()
        label = self.publics.get (sLabel)
        if ( label is None ):
            self.publics[sLabel] = Label (sName, '', None, self.files[-1])
#
    def Label (self, sLabel, bPublic, value = None):
        # self.fList.write ('{:s}, {:s}, {:s}\n'.format (sLabel, str (bPublic), str (value)))
        sName = sLabel
        if ( self.files ):
            tLoc = self.files[-1]
        else:
            tLoc = ['Command Line', 0]
        if ( not self.bLabCase ):
            sLabel = sLabel.lower ()
        bPC = False
        seg = 'A'
        if ( value is None ):
            bPC = True
            seg = self.pseg
            value = self.pc[self.pseg]
        # self.fList.write ('value = ' + str (value) + '\n')
        label = self.publics.get (sLabel)
        if ( label is not None ):
            # self.fList.write ('Exists as public. id(label) = 0x{:X} id(publics) = 0x%{:X}\n'
            #                   .format (id (label), id (self.publics[sLabel])))
            if ( not bPublic ):
                if ( label.file == tLoc[0] ):
                    bPublic = True
                else:
                    label = None
        elif ( not bPublic ):
            label = self.labels.get (sLabel)
        if ( label is None ):
            label = Label (sName, seg, value, tLoc)
            if ( bPublic ):
                # self.fList.write ('Created as public.\n')
                self.publics[sLabel] = label
            else:
                # self.fList.write ('Created as local.\n')
                self.labels[sLabel] = label
        elif ( self.phase == 1 ):
            # if ( not bPublic ):
            #     self.fList.write ('Exists as local 1. id(label) = 0x{:X} id(local) = 0x{:X}\n'
            #                       .format (id (label), id (self.labels[sLabel])))
            if ( label.value is None ):
                label.seg = seg
                label.value = value
                label.file = tLoc[0]
                label.line = tLoc[1]
            else:
                if ( ( self.bStrict ) or ( label.value != value ) ):
                    self.AsmErr ('Duplicate / inconsistent definition of label '
                                 '(0x{:04X} in {:s}/{:d}, 0x{:04X} in {:s}/{:d})'
                                 .format (label.value, label.file,
                                          label.line, value, tLoc[0],
                                          tLoc[1]))
        else:
            # if ( not bPublic ):
            #     self.fList.write ('Exists as local 2. id(label) = 0x%{:X} id(local) = 0x{:X}\n'
            #                       .format (id (label), id (self.labels[sLabel])))
            if ( label.value is None ):
                self.AsmErr ('Label value not set in pass 1')
            elif ( label.value != value ):
                self.AsmErr ('Label address not consistent between passes '
                             '(0x{:04X} in pass 1, 0x{:04X} in pass 2)'
                             .format (label.value, value))
        # label = self.publics.get ('RWGO')
        # if ( label is not None ):
        #     self.fList.write ('publics[RWGO] = {:s}, value = {:s}\n'.format (str (label), str (label.value)))
#
    def Code (self, byCode):
        if ( isinstance (byCode, (bytes, bytearray)) ):
            self.mc += byCode
        elif ( isinstance (byCode, int) ):
            self.mc.append (byCode)
        elif ( isinstance (byCode, str) ):
            self.mc += byCode.encode (encoding='latin_1')
        else:
            self.AsmErr ('Invalid data type for Code (): ' + str (byCode))
#
    def Address (self, ad):
        if ( ad < 0 ):
            ad += 0x10000
        if (( self.phase == 2 ) and (( ad < 0 ) or ( ad > 0xFFFF ))):
            self.AsmErr ('Address {:s} out of range'.format (HexFmt (ad, 4)))
            self.Code (bytes (2))
        else:
            self.Code (ad & 0xFF)
            self.Code ((ad >> 8) & 0xFF)
#
#   Identify all the terms forming an epression
#
    def ExprParse (self, sExpr, bUpdate):
        lExpr = []
        nBrk = 0
        state = self.exStart
        iCh = 0
        nCh = len (sExpr)
        chQuote = None
        while ( iCh < nCh ):
            ch = sExpr[iCh]
            if ( state == self.exStart ):
                if ( ch.isspace () ):
                    iCh += 1
                elif ( ch == '(' ):
                    lExpr.append ((ch,))
                    nBrk += 1
                    iCh += 1
                elif ( ( self.style == 'MA' ) and ( sExpr[iCh:].upper ().startswith ('+ASC"') ) ):
                    chQuote = '"'
                    sValue = ''
                    state = self.exASCII
                    iCh += 5
                elif ( ch in '+-~' ):
                    lExpr.append (('U'+ch,))
                    iCh += 1
                    # state = self.exValue
                else:
                    state = self.exValue
            elif ( state == self.exValue ):
                sValue = ''
                if ( ch.isspace () ):
                    pass
                elif ( ch == '#' ):
                    state = self.exHex
                elif ( ( ch == '&' ) and ( self.style in ('MA', 'PASMO') ) ):
                    state = self.exHex
                elif ( ( ch == '$' ) and ( self.style == 'PASMO' ) ):
                    state = self.exHex
                elif ( ( ch == '%' ) and ( self.style in ('MA', 'PASMO') ) ):
                    state = self.exBinary
                elif ( ch in '0123456789' ):
                    sValue += ch
                    state = self.exNumber
                    # if ( self.style in ('M80', 'PASMO') ):
                    #     state = self.exNumber
                    # else:
                    #     state = self.exDecimal
                elif ( sExpr[iCh:].startswith ("X'") ):
                    chQuote = "'"
                    state = self.exHex
                    iCh += 2
                elif ( ( ch == '"' ) or ( ch == "'" ) ):
                    chQuote = ch
                    sValue = ''
                    state = self.exASCII
                elif ( ( ch.isalpha () ) or ( ch in self.chLabel ) ):
                    sValue = ch
                    state = self.exLabel
                else:
                    self.AsmErr ('Invalid character at start of value: ' + sExpr[iCh:])
                    break
                iCh += 1
            elif ( state == self.exBinary ):
                if ( ch in '01' ):
                    sValue += ch
                    iCh += 1
                else:
                    try:
                        lExpr.append (('B', int (sValue, 2)))
                    except ValueError as e:
                        self.AsmErr (str (e))
                        break
                    state = self.exOperator
            elif ( state == self.exDecimal ):
                if ( ch in '0123456789' ):
                    sValue += ch
                    iCh += 1
                else:
                    try:
                        lExpr.append (('D', int (sValue, 10)))
                    except ValueError as e:
                        self.AsmErr (str (e))
                        break
                    state = self.exOperator
            elif ( state == self.exHex ):
                if ( ch in '0123456789ABCDEFabcdef' ):
                    sValue += ch
                    iCh += 1
                else:
                    if (( sValue == '' ) and ( self.style == 'PASMO' )):
                        lExpr.append (('L', '$'))
                    else:
                        try:
                            lExpr.append (('H', int (sValue, 16)))
                        except ValueError as e:
                            self.AsmErr (str (e))
                            break
                    state = self.exOperator
                    if ( ch == chQuote ):
                        chQuote = None
                        iCh += 1
                    elif ( ( not self.bStrict ) and ( ch in 'Hh' ) ):
                        iCh += 1
            elif ( state == self.exNumber ):
                if ( ch in '0123456789ABCDEFabcdef' ):
                    sValue += ch
                    iCh += 1
                elif ( ( ch in 'Xx' ) and ( sValue == '0' ) ):
                    sValue = ''
                    state = self.exHex
                    iCh += 1
                elif ( ch in 'OQq' ):
                    try:
                        lExpr.append (('Q', int (sValue, 8)))
                    except ValueError as e:
                        self.AsmErr (str (e))
                        break
                    state = self.exOperator
                    iCh += 1
                elif ( ch in 'Hh' ):
                    try:
                        lExpr.append (('H', int (sValue, 16)))
                    except ValueError as e:
                        self.AsmErr (str (e))
                        break
                    state = self.exOperator
                    iCh += 1
                else:
                    try:
                        if ( sValue[-1] in 'Bb' ):
                            lExpr.append (('B', int (sValue[0:-1], 2)))
                        elif ( sValue[-1] in 'Dd' ):
                            lExpr.append (('D', int (sValue[0:-1], 10)))
                        else:
                            lExpr.append (('D', int (sValue, 10)))
                    except ValueError:
                        # self.AsmErr ('Invalid numeric value: ' + sValue)
                        self.AsmErr (str (e))
                        break
                    state = self.exOperator
            elif ( state == self.exASCII ):
                if ( ch == chQuote ):
                    if ( sExpr[iCh:].startswith (chQuote * 2) ):
                        sValue += chQuote
                        iCh += 2
                    else:
                        lExpr.append (('"', sValue))
                        state = self.exOperator
                        chQuote = None
                        iCh += 1
                else:
                    sValue += ch
                    iCh += 1
            elif ( state == self.exLabel ):
                if ( ( ch.isalnum () ) or ( ch in self.chLabel ) ):
                    sValue += ch
                    iCh += 1
                elif ( sValue.upper () == 'NOT' ):
                    lExpr.append (('NOT',))
                    sValue = ''
                    state = self.exStart
                elif ( sValue.upper () == 'LOG2' ):
                    lExpr.append (('L2',))
                    sValue = ''
                    state = self.exStart
                else:
                    lExpr.append (('L', sValue))
                    state = self.exOperator
            elif ( state == self.exOperator ):
                if ( ch.isspace () ):
                    iCh += 1
                elif ( ch == ')' ):
                    nBrk -= 1
                    if ( nBrk < 0 ):
                        self.AsmErr ('Too many closing brackets')
                        break
                    lExpr.append ((')',))
                    iCh += 1
                elif ( sExpr[iCh:].startswith ('<<') ):
                    lExpr.append (('SHL',))
                    state = self.exStart
                    iCh += 2
                elif ( sExpr[iCh:].startswith ('>>') ):
                    lExpr.append (('SHR',))
                    state = self.exStart
                    iCh += 2
                elif ( ch == '=' ):
                    if ( sExpr[iCh:].startswith ('==') ):
                        iCh += 1
                    lExpr.append (('EQ',))
                    state = self.exStart
                    iCh += 1
                elif ( sExpr[iCh:].startswith ('!=') ):
                    lExpr.append (('NE',))
                    state = self.exStart
                    iCh += 2
                elif ( sExpr[iCh:].startswith ('<=') ):
                    lExpr.append (('LE',))
                    state = self.exStart
                    iCh += 2
                elif ( sExpr[iCh:].startswith ('>=') ):
                    lExpr.append (('GE',))
                    state = self.exStart
                    iCh += 2
                elif ( ch == '<' ):
                    if ( self.style == 'MA' ):
                        lExpr.append (('SHL',))
                    else:
                        lExpr.append (('LT',))
                    state = self.exStart
                    iCh += 1
                elif ( ch == '>' ):
                    if ( self.style == 'MA' ):
                        lExpr.append (('SHR',))
                    else:
                        lExpr.append (('GT',))
                    state = self.exStart
                    iCh += 1
                elif ( ch in '+-*/&!^' ):
                    lExpr.append ((ch,))
                    state = self.exStart
                    iCh += 1
                elif ( ch == ',' ):
                    break
                elif ( ch.isalpha () ):
                    sValue = ch
                    state = self.exOpWord
                    iCh += 1
                else:
                    self.AsmErr ('Invalid binary operator: ' + sExpr[iCh:])
                    break
            elif ( state == self.exOpWord ):
                if ( ch.isalpha () ):
                    sValue += ch
                    iCh += 1
                else:
                    sValue = sValue.upper ()
                    if ( sValue in ['LOW', 'HIGH', 'MOD', 'SHL', 'SHR', 'EQ', 'NE',
                                    'LT', 'LE', 'GE', 'GT', 'AND', 'OR', 'XOR'] ):
                        lExpr.append ((sValue,))
                        state = self.exStart
                    else:
                        self.AsmErr ('Invalid operator word: ' + sValue)
                        break
        if ( state == self.exValue ):
            self.AsmErr ('Expecting a value')
        elif ( state == self.exBinary ):
            try:
                lExpr.append (('B', int (sValue, 2)))
            except ValueError as e:
                self.AsmErr (str (e))
        elif ( state == self.exDecimal ):
            try:
                lExpr.append (('D', int (sValue, 10)))
            except ValueError as e:
                self.AsmErr (str (e))
        elif ( state == self.exHex ):
            if (( sValue == '' ) and ( self.style == 'PASMO' )):
                lExpr.append (('L', '$'))
            else:
                try:
                    lExpr.append (('H', int (sValue, 16)))
                except ValueError as e:
                    self.AsmErr (str (e))
        elif ( state == self.exNumber ):
            try:
                if ( sValue[-1] == 'B' ):
                    lExpr.append (('B', int (sValue[0:-1], 2)))
                elif ( sValue[-1] == 'D' ):
                    lExpr.append (('D', int (sValue[0:-1], 10)))
                else:
                    lExpr.append (('D', int (sValue, 10)))
            except ValueError as e:
                self.AsmErr (str (e))
        elif ( state == self.exASCII ):
            if ( self.bStrict ):
                self.AsmErr ('Missing closing quote')
            elif (( self.style == 'MA' ) and ( self.eval == 0 )):
                # MA's original assembler drops last character in this case (new one does not)
                lExpr.append (('"', sValue[0:-1]))
            else:
                lExpr.append (('"', sValue))
        elif ( state == self.exLabel ):
            lExpr.append (('L', sValue))
        elif ( state == self.exOpWord ):
            self.AsmErr ('Incomplete operator word')
        if ( nBrk > 0 ):
            self.AsmErr ('Too many open brackets')
        lExpr.append ((',',))
        if ( bUpdate ):
            if ( iCh == nCh ):
                self.sArgs = ''
            elif ( sExpr == ',' ):
                self.sArgs = sExpr[iCh+1:].strip ()
            else:
                self.PopArg ()
        elif ( iCh < nCh ):
            self.AsmErr ('Unexpected parameters: ' + self.sArgs[iCh:])
        return lExpr
#
    def ExprEval (self, lExpr):
        lValue = []
        lOp = []
        for t in lExpr:
            term = t[0]
            arg = t[-1]
            if ( term in 'BDHQ' ):
                lValue.append (arg)
            elif ( term == '"' ):
                if ( len (arg) == 0 ):
                    lValue.append (0)
                elif ( len (arg) == 1 ):
                    lValue.append (ord (arg))
                else:
                    lValue.append (256 * ord (arg[-2]) + ord (arg[-1]))
            elif ( term == 'L' ):
                if ( not self.bLabCase ):
                    arg = arg.lower ()
                rValue = None
                label = self.labels.get (arg)
                if ( label is None ):
                    label = self.publics.get (arg)
                if ( label is not None ):
                    if ( label.value is not None ):
                        rValue = label.value + self.base[label.seg]
                if ( rValue is None ):
                    if ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
                        # self.fList.write ('label = ' + str (label) + '\n')
                        # self.fList.write ('Publics: ' + str (self.publics) + '\n')
                        # self.fList.write ('Locals: ' + str (self.labels) + '\n')
                        self.AsmErr ('Undefined label: ' + arg)
                        return 0
                    rValue = 0
                lValue.append (rValue)
            elif ( term == '(' ):
                lOp.append ((self.evLvl[self.eval][term], term))
            else:
                rl = self.evLvl[self.eval][term]
                while ( lOp ):
                    if ( lOp[-1][0] < rl ):
                        break
                    op = lOp.pop ()[1]
                    try:
                        if ( op == '+' ):
                            rValue = lValue.pop ()
                            lValue[-1] = lValue[-1] + rValue
                        elif ( op == '-' ):
                            rValue = lValue.pop ()
                            lValue[-1] = lValue[-1] - rValue
                        elif ( op == 'U+' ):
                            pass
                        elif ( op == 'U-' ):
                            lValue[-1] = - lValue[-1]
                        elif ( op in ['U~', 'NOT'] ):
                            lValue[-1] ^= 0xFFFF
                        elif ( op == '*' ):
                            rValue = lValue.pop ()
                            lValue[-1] = lValue[-1] * rValue
                        elif ( op == '/' ):
                            rValue = lValue.pop ()
                            lValue[-1] = lValue[-1] // rValue
                        elif ( op == 'MOD' ):
                            rValue = lValue.pop ()
                            lValue[-1] = lValue[-1] % rValue
                        elif ( op == 'HIGH' ):
                            lValue[-1] >>= 8;
                        elif ( op == 'LOW' ):
                            lValue[-1] &= 0xFF;
                        elif ( op == 'SHL' ):
                            rValue = lValue.pop ()
                            if ( rValue >= 0 ):
                                lValue[-1] = ( lValue[-1] << rValue ) & 0xFFFF
                            else:
                                self.AsmErr ('Negative shift value: {:d}'.format (rValue))
                        elif ( op == 'SHR' ):
                            rValue = lValue.pop ()
                            if ( rValue >= 0 ):
                                lValue[-1] >>= rValue
                            else:
                                self.AsmErr ('Negative shift value: {:d}'.format (rValue))
                        elif ( op == 'L2' ):
                            nBit = 0
                            w = lValue[-1] >> 1
                            while ( w != 0 ):
                                w >>= 1
                                nBit += 1
                            lValue[-1] = nBit
                        elif ( op == 'EQ' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] == rValue, 0xFFFF, 0)
                        elif ( op == 'NE' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] != rValue, 0xFFFF, 0)
                        elif ( op == 'LT' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] < rValue, 0xFFFF, 0)
                        elif ( op == 'LE' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] <= rValue, 0xFFFF, 0)
                        elif ( op == 'GE' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] >= rValue, 0xFFFF, 0)
                        elif ( op == 'GT' ):
                            rValue = lValue.pop ()
                            lValue[-1] = TriArg (lValue[-1] > rValue, 0xFFFF, 0)
                        elif ( op in ['&', 'AND'] ):
                            rValue = lValue.pop ()
                            lValue[-1] &= rValue
                        elif ( op in ['!', 'OR'] ):
                            rValue = lValue.pop ()
                            lValue[-1] |= rValue
                        elif ( op in ['^', 'XOR'] ):
                            rValue = lValue.pop ()
                            lValue[-1] ^= rValue
                        elif ( op == '(' ):
                            break
                        else:
                            sErr = 'Invalid expression operator: ' + op
                            if ( self.bDebug ):
                                sErr += ( '\nlExpr = ' + str (lExpr)
                                          + '\nlValue = ' + str (lValue)
                                          + '\nlOP = ' + str (lOp) )
                            self.AsmErr (sErr)
                            return 0
                    except IndexError:
                        sErr = 'Expression evaluation error'
                        if ( self.bDebug ):
                            sErr += ( '\nlExpr = ' + str (lExpr)
                                      + '\nlValue = ' + str (lValue)
                                      + '\nlOP = ' + str (lOp) )
                        self.AsmErr (sErr)
                        return 0
                if ( term == ')' ):
                    if ( op != '(' ):
                        sErr = 'Mismatched brackets'
                        if ( self.bDebug ):
                            sErr += ( '\nlExpr = ' + str (lExpr)
                                      + '\nlValue = ' + str (lValue)
                                      + '\nlOP = ' + str (lOp) )
                        self.AsmErr (sErr)
                        return 0
                elif ( term == ',' ):
                    break
                else:
                    lOp.append ((self.evLvl[self.eval][term], term))
        if ( ( len (lOp) != 0 ) or ( len (lValue) != 1 ) ):
            sErr = 'Expression evaluation error'
            if ( self.bDebug ):
                sErr += ( '\nlExpr = ' + str (lExpr)
                          + '\nlValue = ' + str (lValue)
                          + '\nlOP = ' + str (lOp) )
            self.AsmErr (sErr)
            return 0
        return lValue[0]
#
    def EvalArith (self, sExpr, bUpdate = False):
        lExpr = self.ExprParse (sExpr, bUpdate)
        if ( lExpr is None ):
            lExpr = [('H', 0), (',',)]
        self.ref.AddArg (lExpr)
        return self.ExprEval (lExpr)
#
    def EvalArith16 (self, sExpr, bUpdate = False):
        value = self.EvalArith (sExpr, bUpdate)
        if (( value >= -0x8000 ) and ( value <= 0xFFFF )):
            return ( value & 0xFFFF )
        elif ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
            self.AsmErr ('Invalid 16-bit value')
        return 0
#
    def EvalArithS8 (self, sExpr, sErr):
        value = self.EvalArith (sExpr)
        if (( value >= -0x80 ) and ( value <= 0x7F )):
            return ( value & 0xFF )
        elif ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
            self.AsmErr (sErr)
        return 0
#
    def EvalIdxAddr (self, sExpr, sErr):
        nCh2 = -1
        nCh1 = sExpr.find ('+')
        if ( nCh1 < 0 ):
            nCh1 = sExpr.find ('-')
        if ( nCh1 > 0 ):
            nCh2 = sExpr.rfind (')', nCh1)
        if ( ( nCh1 < 0 ) or ( nCh2 < 0 ) ):
            sExpr = '+0'
            nCh1 = 0
            nCh2 = 2
        return self.EvalArithS8 (sExpr[nCh1:nCh2], sErr)
#
    def EvalArithU8 (self, sExpr, sErr):
        value = self.EvalArith (sExpr)
        if (( value >= 0 ) and ( value <= 0xFF )):
            return ( value & 0xFF )
        elif ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
            self.AsmErr ('{:s}: 0x{:04X}'.format (sErr, value))
        return 0
#
    def EvalArith8 (self, sExpr, sErr):
        value = self.EvalArith (sExpr)
        if (( value >= 0xFF00 ) and ( value <= 0xFFFF )):
            return ( value & 0xFF )
        if (( value > -0x80 ) and ( value <= 0xFF )):
            return ( value & 0xFF )
        elif ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
            self.AsmErr (sErr)
        return 0
#
    def EvalString (self, sExpr, bUpdate = False):
        lExpr = self.ExprParse (sExpr, bUpdate)
        self.ref.AddArg (lExpr)
        if ( ( len (lExpr) == 2 ) and ( lExpr[0][0] == '"' ) ):
            if ( self.style == 'ZASM' ):
                byStr = bytearray ()
                mode = 0
                for ch in lExpr[0][1]:
                    if ( mode == 0 ):
                        if ( ch == '\\' ):
                            mode = 1
                        else:
                            byStr.append (ord(ch))
                    elif ( mode == 1 ):
                        if ( ch == '\\' ):
                            byStr.append (b'\\')
                            mode = 0
                        else:
                            sHex = ch
                            mode = 2
                    else:
                        sHex += ch
                        byStr.append (int (sHex, 16))
                        mode = 0
            else:
                try:
                    byStr = bytearray (lExpr[0][1], encoding='latin_1')
                except UnicodeError:
                    self.AsmErr ('Invalid 7-bit ASCII character in string: ' + lExpr[0][1])
                    return bytearray (1)
            return byStr
        value = self.ExprEval (lExpr)
        if ( ( self.phase == 2 ) and ( self.enable[-1] ) and ( value > 0xFF ) and ( value < 0xFF80 ) ):
            self.AsmErr ('Invalid byte value: {:s} = 0x{:02X}'.format (sExpr, value))
            return bytearray (1)
        return bytearray ((value & 0xFF,))
#
    def IndexAddr (self, sArg):
        if ( not sArg.endswith (')') ):
            return False
        if ( ( sArg.startswith ('(IX+') ) or ( sArg.startswith ('(IX-') ) or ( sArg == '(IX)' ) ):
            self.ref.AddArg ('(IX')
            self.Code (0xDD)
            return True
        if ( ( sArg.startswith ('(IY+') ) or ( sArg.startswith ('(IY-') ) or ( sArg == '(IY)' ) ):
            self.ref.AddArg ('(IX')
            self.Code (0xFD)
            return True
        return False
#
    def Reg8Opcode (self, sArg, byCode, byPrefix = None, byConst = None, byAddr = None, mult = 1):
        sArgU = sArg.upper ().replace (' ', '')
        byReg = self.reg8X.get (sArgU)
        if ( byReg is not None ):
            self.ref.AddArg (sArgU)
            if ( byPrefix is not None ):
                self.Code (byPrefix)
            self.Code (byCode + mult * byReg)
        elif ( self.IndexAddr (sArgU) ):
            if ( byPrefix is not None ):
                self.Code (byPrefix)
                self.Code (self.EvalIdxAddr (sArg, 'Index out of range'))
                self.Code (byCode + mult * 0x06)
            else:
                self.Code (byCode + mult * 0x06)
                self.Code (self.EvalIdxAddr (sArg, 'Index out of range'))
        elif ( ( sArg.startswith ('(') ) and ( sArg.endswith (')') ) ):
            if ( byAddr is not None ):
                self.ref.AddArg ('(')
                if ( byPrefix is not None ):
                    self.Code (byPrefix)
                self.Code (byAddr)
                self.Address (self.EvalArith16 (sArg[1:-1]))
            else:
                self.AsmErr ('Address argument not valid')
        elif ( byConst is not None ):
            if ( byPrefix is not None ):
                self.Code (byPrefix)
            self.Code (byConst)
            self.Code (self.EvalArith8 (sArg, 'Invalid 8-bit constant'))
        else:
            self.AsmErr ('Invalid argument')
#
    def IndexReg (self, sArg):
        if ( sArg == 'HL' ):
            return True
        byIndex = self.regI.get (sArg)
        if ( byIndex is not None ):
            self.Code (byIndex)
            return True
        return False
#
    def NumArgs (self, bSpace = False):
        if ( bSpace ):
            return CountFields (self.sArgs, ', \t')
        return CountFields (self.sArgs, ',')
#
    def PopArg (self, bSpace = False):
        if ( self.sArgs == '' ):
            self.AsmErr ('Missing argument')
            return ''
        nCh = FindChar (self.sArgs, ',')
        if ( ( nCh < 0 ) and ( bSpace ) ):
            nCh = FindChar (self.sArgs, ' \t')
        if ( nCh >= 0 ):
            sArg = self.sArgs[0:nCh].strip ()
            self.sArgs = self.sArgs[nCh+1:].strip ()
        else:
            sArg = self.sArgs
            self.sArgs = ''
        return sArg
#
    def EndArgs (self):
        if ( self.sArgs != '' ):
            self.AsmErr ('Unexpected argument')
#
    def SetLoad (self, addr, bInit = True):
        if (( not self.bUpdate ) and ( addr < self.lc[self.lseg] )):
            self.AsmErr ('Potential overwite of previous code')
        self.lc[self.lseg] = addr
        if ( self.phase == 2 ):
            if ( self.binout ):
                self.binout.SetAddr (self.lc[self.lseg], bInit)
            if ( self.hexout ):
                self.hexout.SetAddr (self.lc[self.lseg], bInit)
#
    def Parse (self, sLine):
        # Initialise
        self.sErr = None
        self.mc = bytearray ()
        self.nSpace = 0
        self.ltype = 'A'
        # .PRINTX continuation lines
        if ( self.chComment ):
            self.ref.CmntLine (sLine)
            nCh = sLine.find (self.chComment)
            if ( nCh >= 0 ):
                if ( self.bPrintX and self.enable[-1] ):
                    print (sLine[0:nCh])
                self.chComment = None
            elif ( self.bPrintX and self.enable[-1] ):
                print (sLine)
            self.ltype = 'C'
            return
        # Skip blank lines
        sLine = sLine.strip ()
        if ( sLine == '' ):
            self.ltype = 'C'
            return
        # Whole line comments
        if ( sLine.startswith (';') ):
            self.ref.CmntLine (sLine)
            self.ltype = 'C'
            return
        # Automatic labels
        auto = self.labels['$']
        auto.seg = self.pseg
        auto.value = self.pc[self.pseg]
        auto.line = self.files[-1][1]
        # Save and strip trailing comment
        nCmnt = FindChar (sLine, ';')
        if ( nCmnt >= 0 ):
            self.ref.Comment (sLine[nCmnt:])
            sLine = sLine[0:nCmnt].strip ()
        # Test for MA style label
        if ( self.style == 'MA' ):
            if ( sLine[0] == '.' ):
                sLabel = sLine[1:].split (None, 1)[0]
                if ( self.enable[-1] ):
                    self.Label (sLabel, True)
                    self.ref.Label (sLabel)
                return
        # Test for traditional label
        sLabel = None
        sDefine = None
        nCh = FindChar (sLine, ' \t:' )
        if ( nCh >= 0 ):
            if ( sLine[nCh] == ':' ):
                bPublic = False
                sLabel = sLine[0:nCh]
                sLine = sLine[nCh+1:].strip ()
                if ( sLine.startswith (':') ):
                    bPublic = True
                    sLine = sLine[1:].strip ()
                nCh = FindChar (sLine, ' \t' )
            elif ( sLine.split (None, 2)[1].upper () == 'EQU' ):
                bPublic = False
                sLabel = sLine[0:nCh]
                sLine = sLine[nCh:].strip ()
                nCh = FindChar (sLine, ' \t' )
        if ( nCh >= 0 ):
            sDefine = sLine[0:nCh]
            sOpCode = sDefine.upper ()
            self.sArgs = sLine[nCh:].strip ()
        else:
            sOpCode = sLine.upper ()
            self.sArgs = ''
        # Equates and Labels (traditional)
        if ( sOpCode == 'EQU' ):
            self.ref.OpCode (sOpCode)
            self.ref.Label (sLabel)
            if ( sLabel is None ):
                self.AsmErr ('EQUate with no label')
                return
            if ( self.enable[-1] ):
                self.ltype = 'E'
                self.eq = self.EvalArith (self.sArgs, True)
                self.Label (sLabel, bPublic, self.eq)
            return
        if ( sLabel ):
            if ( self.enable[-1] ):
                self.Label (sLabel, bPublic)
            self.ref.Label (sLabel)
        if ( sOpCode == '' ):
            return
        # Pseudo-ops
        if ( sOpCode == 'END' ):
            if ( self.enable[-1] ):
                if ( self.sArgs > '' ):
                    self.begin = self.EvalArith16 (self.sArgs, True)
                self.ltype = 'P'
                return 'X'
            return
        if ( sOpCode in ['LIST', '.LIST'] ):
            self.ref.OpCode (sOpCode)
            self.bList[True] = True
            self.bList[False] = self.bListCond or self.bDebug
            self.ltype = 'P'
            return
        if ( sOpCode in ['NOLIST', '.XLIST'] ):
            self.ref.OpCode (sOpCode)
            self.bList[True] = self.bListForce or self.bDebug
            self.bList[False] = ( self.bListForce and self.bListCond ) or self.bDebug
            self.ltype = 'P'
            return
        if ( sOpCode == '.LFCOND' ):
            self.ref.OpCode (sOpCode)
            self.bList[False] = True
            self.ltype = 'P'
            return
        if ( sOpCode == '.SFCOND' ):
            self.ref.OpCode (sOpCode)
            self.bList[False] = False
            self.ltype = 'P'
            return
        if ( sOpCode == '.TFCOND' ):
            self.ref.OpCode (sOpCode)
            self.bListCond = not self.bListCond
            self.bList[False] = self.bListCond
            self.ltype = 'P'
            return
        if ( sOpCode in ['NAME', 'NAMEX', 'TITLE'] ):
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            self.ltype = 'P'
            return
        if ( sOpCode == 'INCLUDE' ):
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            self.ltype = 'P'
            if ( self.enable[-1] ):
                return 'I'
            return
        if ( sOpCode in ['INSERT', 'INCBIN'] ):
            self.ref.OpCode ('INSERT')
            self.ref.AddArg (self.sArgs)
            self.ltype = 'P'
            if ( self.enable[-1] ):
                self.Insert (self.sArgs)
            return
        if ( sOpCode == 'IFDEF' ):
            self.ref.OpCode (sOpCode)
            label = self.publics.get (self.sArgs)
            if ( label is None ):
                label = self.labels.get (self.sArgs)
            self.enable.append (( self.enable[-1] ) and ( label is not None ))
            self.ltype = 'P'
            return
        if ( sOpCode in ['IF', 'IFT'] ):
            self.ref.OpCode (sOpCode)
            self.enable.append (( self.enable[-1] ) and ( self.EvalArith16 (self.sArgs, True) != 0 ))
            self.ltype = 'P'
            return
        if ( sOpCode in ['IFF', 'IFNOT'] ):
            self.ref.OpCode (sOpCode)
            self.enable.append (( self.enable[-1] ) and ( self.EvalArith16 (self.sArgs, True) == 0 ))
            self.ltype = 'P'
            return
        if ( sOpCode == 'ELSE' ):
            self.ref.OpCode (sOpCode)
            if ( len (self.enable) >= 2 ):
                self.enable[-1] = self.enable[-2] and (not self.enable[-1])
            else:
                self.AsmErr ('ELSE without IF')
            self.ltype = 'P'
            return
        if ( sOpCode == 'ENDIF' ):
            self.ref.OpCode (sOpCode)
            self.ltype = 'P'
            if ( len (self.enable) < 2 ):
                self.AsmErr ('ENDIF with no corresponding IF')
                return
            self.bSkipList = not self.enable[-1]
            self.enable.pop ()
            return
        if ( sOpCode == 'REPT' ):
            if ( self.enable[-1] ):
                nRept = self.EvalArith (self.sArgs, True)
                if ( nRept > 0 ):
                    self.macros.append (['R', self.handles[-1], self.handles[-1].tell (), nRept])
            return
        if ( sOpCode == 'ENDM' ):
            if ( len (self.macros) == 0 ):
                self.AsmErr ('ENDM without macro')
                return
            macro = self.macros.pop ()
            if ( macro[0] == 'R' ):
                macro[3] -= 1
                if ( macro[3] > 0 ):
                    if ( macro[1] != self.handles[-1] ):
                        self.AsmErr ('Start and end of macro in different files')
                        return
                    macro[1].seek (macro[2])
                    self.macros.append (macro)
                    self.bSkipList = True
            return
        if ( sOpCode in ['.COMMENT', '.PRINTX', '.PRINTF'] ):
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            self.chComment = self.sArgs[0]
            self.bPrintX = sOpCode.startswith ('.PRINT')
            nCh = self.sArgs[1:].find (self.chComment)
            if ( nCh >= 0 ):
                if ( self.bPrintX and self.enable[-1] ):
                    print (self.sArgs[1:nCh])
                self.chComment = None
            elif ( self.enable[-1] ):
                print (self.sArgs[1:])
            self.ltype = 'P'
            return
        if ( sOpCode == 'ERROR' ):
            if ( self.enable[-1] ):
                self.AsmErr (self.EvalString (self.sArgs))
            return
        if ( sOpCode == 'DATE' ):
            self.ref.OpCode (sOpCode)
            self.Code (time.strftime ('%d %b %Y'))
            return
        if ( sOpCode == 'TIME' ):
            self.ref.OpCode (sOpCode)
            self.Code (time.strftime ('%H:%M'))
            return
        if ( sOpCode == 'BUILD' ):
            self.ref.OpCode (sOpCode)
            if ( self.build is None ):
                self.GetBuild ()
            self.Code ('{:d}'.format (self.build).ljust (5))
            return
        if ( sOpCode == 'FILL' ):
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            byCode = self.EvalArith8 (self.sArgs, 'Invalid byte value')
            if ( self.binout ):
                self.binout.SetFill (byCode)
            return
        if ( sOpCode == 'EQUD' ):
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            sArg1 = '{:08X}'.format (int (self.sArgs))
            try:
                byCode = bytearray.fromhex (sArg1)
            except ValueError as e:
                self.AsmErr ('{:s}: {:s}'.format (str (e), sArg1))
                return
            byCode.reverse ()
            self.Code (byCode)
            return
        if ( sOpCode in ['.8080', '.Z80', '.Z180'] ):
            self.ref.OpCode (sOpCode)
            self.cpu_type = sOpCode[1:]
            self.ltype = 'P'
            return
        if ( sOpCode == 'ASEG' ):
            self.ltype = 'P'
            return
        if ( sOpCode in ['ASEG', 'CSEG', 'DSEG'] ):
            self.ref.OpCode (sOpCode)
            if ( self.enable[-1] ):
                self.lseg = sOpCode[0]
                self.pseg = sOpCode[0]
                self.SetLoad (self.lc[self.lseg])
                self.pc[self.pseg] = self.lc[self.lseg] + self.offset
            self.ltype = 'P'
            return
        if ( sOpCode in ['EXT', 'EXTRN', 'ENTRY', 'PUBLIC'] ):
            self.ltype = 'P'
            self.ref.OpCode (sOpCode)
            while ( self.sArgs != '' ):
                sArg1 = self.PopArg ()
                self.ref.AddArg (sArg1)
                if ( self.enable[-1] ):
                    self.Public (sArg1)
            return
        if ( sOpCode == 'EVAL' ):
            self.ltype = 'P'
            self.ref.OpCode (sOpCode)
            self.ref.AddArg (self.sArgs)
            if ( self.sArgs == 'SIMPLE' ):
                self.eval = 1
            elif ( self.sArgs == 'FULL' ):
                self.eval = 0
            else:
                self.AsmErr ('Invalid evaluation type')
            return
        if ( sOpCode == 'LABCASE' ):
            self.ltype = 'P'
            self.ref.OpCode (sOpCode)
            if ( self.sArgs.upper() == 'YES' ):
                self.bLabCase = True
                self.ref.AddArg (self.sArgs)
            if ( self.sArgs.upper() == 'NO' ):
                self.bLabCase = False
                self.ref.AddArg (self.sArgs)
            else:
                self.bLabCase = ( self.EvalArith16 (self.sArgs, True) != 0 )
            return
        # MA specific pseudo-ops
        if ( self.style == 'MA' ):
            if ( sOpCode == 'ORG' ):
                self.bUpdate = 'ORG' in self.lOrgUpd
                address = self.EvalArith (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.SetLoad (address)
                    self.pc[self.pseg] = self.lc[self.lseg] + self.offset
                self.ref.Position ('B', self.offset)
                self.ltype = 'P'
                return
            elif ( sOpCode == 'BORG' ):
                self.bUpdate = 'BORG' in self.lOrgUpd
                address = self.EvalArith16 (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.pc[self.pseg] = address
                    self.SetLoad (self.pc[self.pseg] - self.offset)
                self.ref.Position ('A', self.offset)
                self.ltype = 'P'
                return
            elif ( sOpCode == 'OFFSET' ):
                self.bUpdate = 'OFFSET' in self.lOrgUpd
                if ( self.sArgs > '' ):
                    address = self.EvalArith16 (self.sArgs, True)
                    if ( self.enable[-1] ):
                        self.pseg = 'A'
                        self.pc[self.pseg] = address
                    self.ref.Position ('O')
                else:
                    if ( self.enable[-1] ):
                        self.pseg = self.lseg
                        self.pc[self.pseg] = self.lc[self.lseg]
                    self.ref.Position ('R', self.pc[self.pseg])
                if ( self.enable[-1] ):
                    self.offset = self.pc[self.pseg] - self.lc[self.lseg]
                self.ltype = 'P'
                return
        # M80 specific pseudo-ops
        # PASMO only has ORG, but allow M80 style relocation pseudo-ops
        elif ( self.style in ['M80', 'PASMO'] ):
            if ( sOpCode == 'ORG' ):
                self.bUpdate = 'ORG' in self.lOrgUpd
                address = self.EvalArith (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.SetLoad (address)
                    self.pc[self.pseg] = self.lc[self.lseg]
                self.ref.Position ('B')
                self.ltype = 'P'
                return
            if ( sOpCode == '.PHASE' ):
                self.bUpdate = 'PHASE' in self.lOrgUpd
                address = self.EvalArith16 (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.pseg = 'A'
                    self.pc[self.pseg] = address
                self.ref.Position ('O')
                self.ltype = 'P'
                return
            if ( sOpCode == '.DEPHASE' ):
                self.bUpdate = 'DEPHASE' in self.lOrgUpd
                if ( self.enable[-1] ):
                    self.pseg = self.lseg
                    self.pc[self.pseg] = self.lc[self.lseg]
                self.ref.Position ('R')
                self.ltype = 'P'
                return
        # ZASM specific pseudo-ops
        elif ( self.style == 'ZASM' ):
            if ( sOpCode == 'LOAD' ):
                self.bUpdate = 'LOAD' in self.lOrgUpd
                address = self.EvalArith (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.SetLoad (address)
                self.ref.Position ('B')
                self.ltype = 'P'
                return
            if ( sOpCode == 'ORG' ):
                self.bUpdate = 'ORG' in self.lOrgUpd
                address = self.EvalArith16 (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.pc[self.pseg] = address
                if ( self.pc[self.pseg] != self.lc[self.lseg] ):
                    self.ref.Position ('O')
                self.ltype = 'P'
                return
        # Defines
        if ( sOpCode in ['DB', 'DEFB'] ):
            self.ref.OpCode (sOpCode)
            while ( self.sArgs > '' ):
                self.Code (self.EvalString (self.sArgs, True))
            return
        if ( sOpCode in ['DW', 'DEFW'] ):
            self.ref.OpCode (sOpCode)
            while ( self.sArgs > '' ):
                self.Address (self.EvalArith16 (self.sArgs, True))
            return
        if ( sOpCode in ['DD', 'DEFD'] ):
            self.ref.OpCode (sOpCode)
            while ( self.sArgs > '' ):
                value = self.EvalArith (self.sArgs, True)
                self.Code (value & 0xFF)
                self.Code ((value >> 8) & 0xFF)
                self.Code ((value >> 16) & 0xFF)
                self.Code ((value >> 24) & 0xFF)
            return
        if ( sOpCode in ['DC', 'DEFC'] ):
            while ( self.sArgs > '' ):
                byCode = self.EvalString (self.sArgs, True)
                byCode[-1] |= 0x80
                self.Code (byCode)
            if ( self.style == 'ZASM' ):
                self.ref.StringCode ('C')
            else:
                self.ref.OpCode (sOpCode)
            return
        if ( sOpCode in ['DZ', 'DEFZ'] ):
            while ( self.sArgs > '' ):
                byCode = self.EvalString (self.sArgs, True)
                byCode.append (0)
                self.Code (byCode)
            if ( self.style == 'ZASM' ):
                self.ref.StringCode ('Z')
            else:
                self.ref.OpCode (sOpCode)
            return
        if ( sOpCode in ['DS', 'DEFS'] ):
            if ( self.style in ('M80', 'PASMO') ):
                self.ref.OpCode ('BYTE')
                value = self.EvalArith16 (self.sArgs, True)
                if ( self.enable[-1] ):
                    self.nSpace = value
            else:
                while ( self.sArgs > '' ):
                    self.Code (self.EvalString (self.sArgs, True))
                if ( self.style == 'ZASM' ):
                    self.ref.StringCode ('S')
                else:
                    self.ref.OpCode (sOpCode)
            return
        if ( sOpCode in ['BYTE', 'WORD'] ):
            self.ref.OpCode (sOpCode)
            value = self.EvalArith16 (self.sArgs, True)
            if ( sOpCode == 'WORD' ):
                value *= 2
            if ( self.enable[-1] ):
                self.nSpace = value
            return
        if ( sOpCode in 'ALIGN' ):
            self.ref.OpCode (sOpCode)
            value = self.EvalArith16 (self.sArgs, True)
            if ( value < 0 ):
                self.AsmErr ('Invalid alignment')
            elif ( self.enable[-1] ):
                pad = self.pc[self.pseg] % value
                if ( pad > 0 ):
                    self.nSpace = value - pad
            return
        if ( sOpCode == 'ZERO' ):
            self.ref.OpCode (sOpCode)
            value = self.EvalArith16 (self.sArgs, True)
            self.Code (bytes (value))
            return
        if ( self.cpu_type == '8080' ):
            # 8080 Opcodes
            if ( sOpCode == 'MOV' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg8M.get (sArg1)
                if ( byCode is not None ):
                    byCode = 8 * byCode + 0x40
                    sArg2 = self.PopArg ().upper ()
                    byReg = self.reg8M.get (sArg2)
                    if ( byReg is not None ):
                        byCode += byReg
                        if ( byCode != 0x76 ):
                            self.ref.AddArg (sArg1)
                            self.ref.AddArg (sArg2)
                            self.Code (byCode)
                            return
                self.AsmErr ('Invalid registers for MOV')
                return
            if ( sOpCode == 'MVI' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg8M.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (8 * byCode + 0x06)
                    self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8-bit constant'))
                    return
                self.AsmErr ('Invalid register for MVI')
                return
            if ( sOpCode == 'LDA' ):
                self.ref.OpCode (sOpCode)
                self.Code (0x3A)
                self.Address (self.EvalArith16 (self.sArgs))
                return
            if ( sOpCode == 'STA' ):
                self.ref.OpCode (sOpCode)
                self.Code (0x32)
                self.Address (self.EvalArith16 (self.sArgs))
                return
            if ( sOpCode == 'LDAX' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg16X.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 0x0A)
                    return
                self.AsmErr ('Invalid registers for STAX')
                return
            if ( sOpCode == 'STAX' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg16X.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 0x02)
                    return
                self.AsmErr ('Invalid register for STAX')
                return
            if ( sOpCode == 'LXI' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg16O.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 0x01)
                    self.Address (self.EvalArith16 (self.sArgs))
                    return
                self.AsmErr ('Invalid register for LXI')
                return
            if ( sOpCode == 'PUSH' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg16Q.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 0xC5)
                    return
                self.AsmErr ('Invalid register for PUSH')
                return
            if ( sOpCode == 'POP' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byCode = self.reg16Q.get (sArg1)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 0xC1)
                    return
                self.AsmErr ('Invalid register for PUSH')
                return
            byCode = self.op8080Z.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Code (byCode)
                return
            byCode = self.op8080A.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byReg = self.reg8M.get (sArg1)
                if ( byReg is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + byReg)
                    return
                self.AsmErr ('Invalid register')
                return
            byCode = self.op8080I.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byReg = self.reg8M.get (sArg1)
                if ( byReg is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + 8 * byReg)
                    return
                self.AsmErr ('Invalid register')
                return
            byCode = self.op8080X.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Code (byCode)
                self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8-bit constant'))
                return
            byCode = self.op8080D.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                byReg = self.reg16O.get (sArg1)
                if ( byReg is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode + byReg)
                    return
                self.AsmErr ('Invalid register')
                return
            byCode = self.op8080C.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Code (byCode)
                self.Address (self.EvalArith16 (self.sArgs))
                return
            if ( sOpCode == 'RST' ):
                self.ref.OpCode (sOpCode)
                byCode = self.EvalArith16 (self.sArgs)
                if ( ( byCode >= 0 ) and ( byCode <= 7 ) ):
                    self.Code (8 * byCode + 0xC7)
                    return
                self.AsmErr ('Invalid restart')
                return
        else:
            # Z80 Opcodes
            # Opcode with no parameters
            byCode = self.op0.get (sOpCode)
            if ( byCode is not None ):
                if ( nCh != -1 ):
                    self.AsmErr ('Unexpected arguments to opcode')
                    return
                self.ref.OpCode (sOpCode)
                self.Code (byCode)
                return
            # 8 bit arithmatic
            byCode = self.opA1.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Reg8Opcode (self.sArgs, byCode, byConst = byCode + 0x46)
                return
            # 8 or 16 bit Arithmetic
            byCode = self.opA2.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg (True).upper ()
                if ( sArg1 == 'A' ):
                    self.ref.AddArg (sArg1)
                    self.Reg8Opcode (self.sArgs, byCode, byConst = byCode + 0x46)
                    return
                elif ( sArg1 == 'HL' ):
                    sArg2 = self.PopArg (True).upper ()
                    self.ref.AddArg (sArg1)
                    self.ref.AddArg (sArg2)
                    self.EndArgs ()
                    byCode = self.reg16.get (sArg2)
                    if ( byCode is None ):
                        self.AsmErr ('Invalid source register: ' + sArg2)
                        return
                    if ( sOpCode == 'ADC' ):
                        self.Code (0xED)
                        byCode += 0x4A
                    elif ( sOpCode == 'ADD' ):
                        byCode += 0x09
                    else: # if ( sOpCode == 'SBC' ):
                        self.Code (0xED)
                        byCode += 0x42
                    self.Code (byCode)
                    return
                elif ( ( sOpCode == 'ADD' ) and ( sArg1 in self.regI ) ):
                    sArg2 = self.PopArg (True).upper ()
                    self.ref.AddArg (sArg1)
                    self.ref.AddArg (sArg2)
                    self.EndArgs ()
                    if ( sArg2 == sArg1 ):
                        byCode = 0x20
                    else:
                        byCode = self.reg16.get (sArg2)
                        if ( ( byCode is None ) or ( byCode == 0x20 ) ):
                            self.AsmErr ('Invalid source register: ' + sArg2)
                            return
                    self.Code ( self.regI[sArg1] )
                    self.Code ( byCode + 0x09 )
                    return
                else:
                    self.AsmErr ('Invalid destination register: ' + sArg1)
                    return
            # Bit operations
            byCode = self.opB2.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                nBit = self.EvalArith16 (self.sArgs, True)
                if ( ( nBit < 0 ) or ( nBit > 7 ) ):
                    if ( ( self.phase == 2 ) and ( self.enable[-1] ) ):
                        self.AsmErr ('Invalid bit number: {:d}'.format (nBit))
                        nBit = 0
                        # return
                    nBit &= 0x07
                byCode += 8 * nBit
                self.Reg8Opcode (self.sArgs, byCode, byPrefix = 0xCB)
                return
            # Call and jumps
            if ( sOpCode == 'JMP' ):    # A MA variant
                sOpCode = 'JP'
            byCode = self.opC.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                if ( self.NumArgs (self.style == 'MA') == 1 ):
                    byCode = byCode[0]
                    byCond = 0x00
                    if ( sOpCode == 'JP' ):
                        sArg1 = self.sArgs.upper ()
                        if ( sArg1 == '(HL)' ):
                            self.ref.AddArg (sArg1)
                            self.Code (0xE9)
                            return
                        elif ( sArg1 == '(IX)' ):
                            self.ref.AddArg (sArg1)
                            self.Code (b'\xDD\xE9')
                            return
                        elif ( sArg1 == '(IY)' ):
                            self.ref.AddArg (sArg1)
                            self.Code (b'\xFD\xE9')
                            return
                else:
                    byCode = byCode[1]
                    sArg1 = self.PopArg (self.style == 'MA').upper ()
                    self.ref.AddArg (sArg1)
                    byCond = self.cond.get (sArg1)
                    if ( byCond is None ):
                        self.AsmErr ('Invalid condition code: ' + sArg1)
                        byCond = 0
                        return
                    byCode += byCond
                address = self.EvalArith16 (self.sArgs)
                if ( sOpCode == 'JR' ):
                    if ( byCond >= 0x20 ):
                        self.AsmErr ('Condition code not supported by JR: ' + sArg1)
                        return
                    address -= self.pc[self.pseg] + self.base[self.pseg] + 2
                    if ( ( self.phase == 2 ) and ( self.enable[-1] )
                         and ( ( address < -128 ) or ( address > 127 ) ) ):
                        self.AsmErr ('Relative jump out of range: {:d}'.format (address))
                        address = 0
                    self.Code (byCode)
                    self.Code (address & 0xFF)
                else:
                    self.Code (byCode)
                    self.Address (address)
                return
            # Decrement and Increment
            byCode = self.opD.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.sArgs.upper ()
                byReg = self.reg16.get (sArg1)
                if ( byReg is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byCode[1] + byReg)
                    return
                byReg = self.regI.get (sArg1)
                if ( byReg is not None ):
                    self.ref.AddArg (sArg1)
                    self.Code (byReg)
                    self.Code (byCode[1] + 0x20)
                    return
                self.Reg8Opcode (self.sArgs, byCode[0], mult=8)
                return
            # Loop
            if ( sOpCode == 'DJNZ' ):
                self.ref.OpCode (sOpCode)
                address = self.EvalArith16 (self.sArgs)
                address -= self.pc[self.pseg] + self.base[self.pseg] + 2
                self.Code (0x10)
                self.Code (address & 0xFF)
                if ( ( self.phase == 2 ) and ( self.enable[-1] )
                     and ( ( address < -128 ) or ( address > 127 ) ) ):
                    self.AsmErr ('Relative jump out of range: {:d}'.format (address))
                    return
                return
            # Exchange
            if ( sOpCode == 'EX' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                sArg2 = self.sArgs.upper ()
                self.ref.AddArg (sArg1)
                self.ref.AddArg (sArg2)
                if ( sArg1 == '(SP)' ):
                    if ( self.IndexReg (sArg2) ):
                        self.Code (0xE3)
                        return
                elif ( ( sArg1 == 'DE' ) and ( sArg2 == 'HL' ) ):
                    self.Code (0xEB)
                    return
                elif ( ( sArg1 == 'AF' ) and ( sArg2.startswith ("AF'") ) ):
                    sTmp = sArg2[3:].strip()
                    if ( ( sTmp == '' ) or ( sTmp.startswith (';') ) ):
                        self.Code (0x08)
                        return
                self.AsmErr ('Invalid registers for exchange')
                return
            # Interrupt mode
            if ( sOpCode == 'IM' ):
                self.ref.OpCode (sOpCode)
                mode = self.EvalArith16 (self.sArgs)
                if ( ( mode >= 0 ) and ( mode <= 2 ) ):
                    self.Code ((b'\xED\x46', b'\xED\x56', b'\xED\x5E')[mode])
                    return
                self.AsmErr ('Invalid interrupt mode: {:d}'.format (mode))
                return
            # Port Input
            if ( sOpCode == 'IN' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ().upper ()
                sArg2 = self.sArgs.upper ()
                self.ref.AddArg (sArg1)
                if ( sArg2 == '(C)' ):
                    self.ref.AddArg (sArg2)
                    byCode = self.reg8.get (sArg1)
                    if ( byCode is not None ):
                        self.Code (0xED)
                        self.Code (0x40 + 8 * byCode)
                        return
                if ( sArg1 == 'A' ):
                    self.Code (0xDB)
                    self.Code (self.EvalArithU8 (self.sArgs, 'Invalid port address'))
                    return
                self.AsmErr ('Invalid input instruction')
                return
            # Load
            if ( sOpCode == 'LD' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ()
                sArg1U = sArg1.upper ().replace (' ', '')
                sArg2U = self.sArgs.upper ()
                if ( sArg1U == 'A' ):
                    self.ref.AddArg (sArg1U)
                    byCode = self.regLA.get (sArg2U)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg2U)
                        self.Code (byCode[0])
                        return
                    self.Reg8Opcode (self.sArgs, 0x78, byAddr = 0x3A, byConst = 0x3E)
                    return
                if ( sArg1U == '(HL)' ):
                    self.ref.AddArg (sArg1U)
                    byCode = self.reg8.get (sArg2U)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg2U)
                        self.Code (byCode + 0x70)
                        return
                    self.Code (0x36)
                    self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8 bit constant'))
                    return
                if ( self.IndexAddr (sArg1U) ):
                    byIndex = self.EvalIdxAddr (sArg1, 'Invalid index offset')
                    byCode = self.reg8.get (sArg2U)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg2U)
                        self.Code (byCode + 0x70)
                        self.Code (byIndex)
                        return
                    self.Code (0x36)
                    self.Code (byIndex)
                    self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8 bit constant'))
                    return
                byCode = self.reg8.get (sArg1U)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1U)
                    self.Reg8Opcode (self.sArgs, 0x40 + 8 * byCode, byConst = 0x06 + 8 * byCode)
                    return
                if ( sArg2U == 'A' ):
                    byCode = self.regLA.get (sArg1U)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg1U)
                        self.ref.AddArg (sArg2U)
                        self.Code (byCode[1])
                        return
                    if ( sArg1.startswith ('(') and sArg1.endswith (')') ):
                        self.Code (0x32)
                        self.ref.AddArg ('(')
                        self.Address (self.EvalArith16 (sArg1[1:-1]))
                        self.ref.AddArg (sArg2U)
                        return
                    self.AsmErr ('Invalid 8 bit destination')
                    return
                if ( sArg1U == 'SP' ):
                    if ( self.IndexReg (sArg2U) ):
                        self.ref.AddArg (sArg1U)
                        self.ref.AddArg (sArg2U)
                        self.Code (0xF9)
                        return
                if ( self.IndexReg (sArg1U) ):
                    self.ref.AddArg (sArg1U)
                    if ( sArg2U.startswith ('(') and sArg2U.endswith (')') ):
                        self.ref.AddArg ('(')
                        self.Code (0x2A)
                        self.Address (self.EvalArith16 (self.sArgs[1:-1]))
                        return
                    self.Code (0x21)
                    self.Address (self.EvalArith16 (self.sArgs))
                    return
                byCode = self.reg16.get (sArg1U)
                if ( byCode is not None ):
                    self.ref.AddArg (sArg1U)
                    if ( sArg2U.startswith ('(') and sArg2U.endswith (')') ):
                        self.ref.AddArg ('(')
                        self.Code (0xED)
                        self.Code (byCode + 0x4B)
                        self.Address (self.EvalArith16 (self.sArgs[1:-1]))
                        return
                    self.Code (byCode + 0x01)
                    self.Address (self.EvalArith16 (self.sArgs))
                    return
                if ( self.IndexReg (sArg2U) ):
                    if ( sArg1.startswith ('(') and sArg1.endswith (')') ):
                        self.ref.AddArg ('(')
                        self.Code (0x22)
                        self.Address (self.EvalArith16 (sArg1[1:-1]))
                        self.ref.AddArg (sArg2U)
                        return
                byCode = self.reg16.get (sArg2U)
                if ( byCode is not None ):
                    if ( sArg1.startswith ('(') and sArg1.endswith (')') ):
                        self.ref.AddArg ('(')
                        self.Code (0xED)
                        self.Code (byCode + 0x43)
                        self.Address (self.EvalArith16 (sArg1[1:-1]))
                        self.ref.AddArg (sArg2U)
                        return
                self.AsmErr ('Invalid load instruction')
                return
            # Port Output
            if ( sOpCode == 'OUT' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ()
                sArg1U = sArg1.upper ()
                sArg2U = self.sArgs.upper ()
                if ( sArg1U == '(C)' ):
                    self.ref.AddArg (sArg1U)
                    byCode = self.reg8.get (sArg2U)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg2U)
                        self.Code (0xED)
                        self.Code (0x41 + 8 * byCode)
                        return
                if ( sArg2U == 'A' ):
                    self.Code (0xD3)
                    self.Code (self.EvalArithU8 (sArg1, 'Invalid port address'))
                    self.ref.AddArg (sArg2U)
                    return
                self.AsmErr ('Invalid output instruction')
                return
            # Pop / Push from / to stack
            byCode = self.opP.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.sArgs.upper ()
                self.ref.AddArg (sArg1)
                if ( self.IndexReg (sArg1) ):
                    self.Code (byCode + 0x20)
                    return
                byReg = self.reg16P.get (sArg1)
                if ( byReg is not None ):
                    self.Code (byCode + byReg)
                    return
                self.AsmErr ('Invalid POP / PUSH register')
                return
            # Returns
            if ( sOpCode == 'RET' ):
                self.ref.OpCode (sOpCode)
                if ( self.sArgs == '' ):
                    self.Code (0xC9)
                    return
                sArg1 = self.sArgs.upper ()
                self.ref.AddArg (sArg1)
                byCode = self.cond.get (sArg1)
                if ( byCode is not None ):
                    self.Code (byCode + 0xC0)
                    return
                self.AsmErr ('Invalid return condition')
                return
            # Restart calls
            if ( sOpCode == 'RST' ):
                self.ref.OpCode (sOpCode)
                byCode = self.EvalArith16 (self.sArgs)
                if ( byCode in [0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38] ):
                    self.Code (byCode + 0xC7)
                    return
                self.AsmErr ('Invalid restart address')
                return
            # Rotates and shifts
            byCode = self.opR.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Reg8Opcode (self.sArgs, byCode, byPrefix = 0xCB)
                return
        if ( self.cpu_type == 'Z180' ):
            # Z180 Op-codes
            byCode = self.op180.get (sOpCode)
            if ( byCode is not None ):
                self.ref.OpCode (sOpCode)
                self.Code (0xED)
                self.Code (byCode)
                return
            if ( sOpCode in ['MLT', 'MULT'] ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg (True).upper ()
                self.ref.AddArg (sArg1)
                byCode = self.reg16.get (sArg1)
                if ( byCode is not None ):
                    self.Code (0xED)
                    self.Code (byCode + 0x4C)
                else:
                    self.AsmErr('Missing argument')
                return
            if ( sOpCode == 'IN0' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg (True).upper ()
                byCode = self.reg8F.get (sArg1)
                if ( byCode is not None ):
                    if ( ( self.sArgs.startswith ('(') ) and ( self.sArgs.endswith (')') ) ):
                        self.ref.AddArg (sArg1)
                        self.ref.AddArg ('(')
                        self.Code (0xED)
                        self.Code (8 * byCode)
                        self.Code (self.EvalArithU8 (self.sArgs[1:-1], "Invalid port address"))
                    else:
                        self.AsmErr('Missing brackets around port address')
                else:
                    self.AsmErr('Missing argument')
                return
            if ( sOpCode == 'OUT0' ):
                self.ref.OpCode (sOpCode)
                sArg1 = self.PopArg ()
                sArg2 = self.PopArg (True).upper ()
                byCode = self.reg8F.get (sArg2)
                if ( byCode is not None ):
                    if ( ( sArg1.startswith ('(') ) and ( sArg1.endswith (')') ) ):
                        self.ref.AddArg ('(')
                        self.Code (0xED)
                        self.Code (8 * byCode + 0x01)
                        self.Code (self.EvalArithU8 (sArg1[1:-1], "Invalid port address"))
                        self.ref.AddArg (sArg2)
                    else:
                        self.AsmErr('Missing brackets around port address')
                else:
                    self.AsmErr('Missing argument')
                return
            if ( sOpCode in ['TST', 'TSTIO'] ):
                self.ref.OpCode ('TST')
                if ( sOpCode == 'TSTIO' ):
                    sArg1 = '(C)'
                elif ( self.NumArgs (True) == 1 ):
                    sArg1 = 'A'
                else:
                    sArg1 = self.PopArg (True).upper ()
                self.ref.AddArg (sArg1)
                if ( sArg1 == 'A' ):
                    sArg2 = self.PopArg (True).upper
                    byCode = self.reg8X.get (sArg2)
                    if ( byCode is not None ):
                        self.ref.AddArg (sArg2U)
                        self.Code (0xED)
                        self.Code (8 * byCode + 0x04)
                    else:
                        self.Code (b'\xED\x64')
                        self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8-bit immediate'))
                elif ( sArg1 == '(C)' ):
                    self.Code (b'\xED\x74')
                    self.Code (self.EvalArith8 (self.sArgs, 'Invalid 8-bit immediate'))
                else:
                    self.AsmErr('Invalid argument')
                return
        # MA style EQUates
        if ( sDefine ):
            sArg1 = self.PopArg (True).upper ()
            if ( sArg1 == 'EQU' ):
                self.ref.Label (sDefine)
                self.ref.OpCode (sArg1)
                address = self.EvalArith (self.sArgs)
                if ( self.enable[-1] ):
                    self.ltype = 'E'
                    self.eq = address
                    self.Label (sDefine, False, self.eq)
                return
        self.AsmErr ('Invalid OpCode "{:s}"'.format (sOpCode))
        return
#
#   List assembled code
    def List (self, sLine, sErr):
        if ( self.fList is None):
            return
        if ( self.bSkipList ):
            self.bSkipList = False
            return
        if ( ( self.bList[self.enable[-1]] ) or ( sErr != '' ) ):
            nb = len (self.mc)
            mb = 6
            if ( self.bAddress ):
                mb = 4
            if ( ( self.enable[-1] ) and ( self.ltype == 'A' ) and ( sErr == '' ) ):
                if ( self.bAddress ):
                    laddr = self.lc[self.lseg] + self.base[self.lseg]
                    if ( laddr < 0x10000 ):
                        self.fList.write (' {:04X} '.format (laddr))
                    else:
                        self.fList.write ('{:5X} '.format (laddr))
                self.fList.write ('{:04X}'.format (self.pc[self.pseg] + self.base[self.pseg]))
                for by in self.mc[0:mb]:
                    self.fList.write (' {:02X}'.format (by))
                if ( nb < mb ):
                    self.fList.write ('   ' * ( mb - nb ))
                self.fList.write ('  {:s}'.format (sLine))
                for i, by in enumerate (self.mc[mb:]):
                    if ( i % mb == 0 ):
                        self.fList.write ('\n    ')
                        if ( self.bAddress ):
                            self.fList.write ('      ')
                    self.fList.write (' {:02X}'.format (by))
                self.fList.write ('\n')
            elif ( ( self.enable[-1] ) and ( self.ltype == 'E' ) and ( sErr == '' ) ):
                self.fList.write ('     ')
                mb = 19
                if ( self.bAddress ):
                    self.fList.write ('      ')
                    mb = 13
                sHex = '{:04X}'.format (self.eq)
                mb -= len (sHex)
                self.fList.write (sHex + ( ' ' * mb ) + sLine + '\n')
            else:
                self.fList.write ('                        {:s}\n'.format (sLine))
                if ( sErr > '' ):
                    self.fList.write ('           *** ERROR:   {:s}\n'.format (sErr))
#
    def Debug (self, sMsg):
        if ( self.fList ):
            self.fList.write (sMsg + '\n')
#
#   One pass through a source file:
    def AsmPass (self, sInput):
        self.files.append ([sInput, 0])
        self.srcdir = os.path.dirname (sInput)
        if ( '$' not in self.labels ):
            self.labels['$'] = Label ('$', 'A', 0, self.files[-1])
        nEnable = len (self.enable)
        bEnd = False
        with open (sInput, 'r', encoding='latin_1') as fIn:
            self.handles.append (fIn)
            while (True):
                sLine = fIn.readline ()
                if ( len (sLine) == 0 ):
                    break
                self.files[-1][1] += 1
                sLine = sLine.rstrip ()
                if ( self.bEcho ):
                    print (sLine)
                sErr = ''
                action = self.Parse (sLine)
                if ( self.sErr is not None ):
                    sErr = self.sErr
                    self.nErr += 1
                    if ( not self.bEcho ):
                        print (sLine)
                    print (sErr)
                    print ('in line {:d} of file {:s}'.format (self.files[-1][1], self.files[-1][0]))
                self.List (sLine, sErr)
                if ( self.enable[-1] ):
                    nCode = len (self.mc)
                    if ( nCode > 0 ):
                        self.SetLoad (self.lc[self.lseg], False)
                        if ( self.binout ):
                            self.binout.Data (self.mc)
                        if ( self.hexout ):
                            self.hexout.Data (self.mc)
                    nCode += self.nSpace
                    self.pc[self.pseg] += nCode
                    self.lc[self.lseg] += nCode
                self.ref.Output ()
                if ( action == 'I' ):
                    self.Include (self.sArgs)
                elif ( action == 'X' ):
                    break
        if ( nEnable != len (self.enable) ):
            if (( self.style == 'MA' ) and ( len (self.enable) > nEnable )):
                self.enable = self.enable[0:nEnable]
            else:
                print ('Mismatched IF/ENDIF in file ' + sInput)
                self.nErr += 1
        self.files.pop ()
#
#   Find a folder, ignoring case
    def FindDir (self, sDir):
        # print ("FindDir", sDir)
        if ( sDir == '' ):
            return sDir
        lPath = sDir.lower ().split ('/')
        # sDir = '.'
        sDir = os.getcwd ()
        # print ('cwd = ' + sDir)
        for sPath in lPath:
            # print ('sPath = ' + sPath)
            bFound = False
            if ( sPath == '.' ):
                bFound = True
            elif ( sPath == '..' ):
                bFound = True
                sDir = os.path.dirname (sDir)
            else:
                for sFolder in glob.glob (os.path.join (sDir, '*')):
                    # print ('sFolder = ' + sFolder)
                    sMatch = os.path.basename (sFolder).lower ()
                    if (( os.path.isdir (sFolder)) and ( sMatch == sPath )):
                        bFound = True
                        sDir = sFolder
                        # print ('Matched: sDir = ' + sDir)
                        break
            if ( not bFound ):
                return None
        # print ("Found:", sDir)
        return sDir
#
#   Find a file, ignoring case and processing special characters
    def FindFile (self, sFile, sExt):
        # print ("Find:", sFile)
        if ( ( sFile[0] in '\'"' ) and ( sFile[-1] == sFile[0] ) ):
            sFile = sFile[1:-1]
        if ( self.style == 'MA' ):
            sTemp = ''
            for ch in sFile:
                if ( ch == ',' ):
                    break
                elif ( ch == '/' ):
                    ch = '.'
                elif ( ch == '.' ):
                    ch = '/'
                sTemp += ch
            sFile = sTemp
            sSearch = '*'
        else:
            nCh = sFile.find ('.')
            if ( nCh < 0 ):
                sFile += sExt
            sSearch = '*'
        sDir, sFile = os.path.split (sFile)
        sDir = self.FindDir (sDir)
        if ( sDir is None ):
            return None
        sFile = sFile.lower ()
        # print ("sDir = " + sDir)
        # print ("sFile = " + sFile)
        # print ("sSearch = " + sSearch)
        for sInclude in glob.glob (os.path.join (sDir, sSearch)):
            sMatch = os.path.basename (sInclude).lower ()
            if ( sMatch[-1] == '~' ):
                continue
            # print ("sMatch = " + sMatch)
            if ( self.style == 'MA' ):
                nCh = sMatch.rfind (',')
                if ( nCh > 0 ):
                    sMatch = sMatch[0:nCh]
            if ( sMatch == sFile ):
                return sInclude
        return None
#
#   Find a file, searching include directories
    def FindInclude (self, sFile, sExt):
        if ( ( sFile[0] in '\'"' ) and ( sFile[-1] == sFile[0] ) ):
            sFile = sFile[1:-1]
        sInclude = self.FindFile (sFile, self.sExt)
        if ( sInclude is None ):
            sInclude = self.FindFile (os.path.join (self.srcdir, sFile), self.sExt)
        if (( sInclude is None ) and (self.inc_dirs is not None)):
            for sDir in self.inc_dirs:
                sInclude = self.FindFile (os.path.join (sDir, sFile), self.sExt)
                if ( sInclude is not None ):
                    break
        return sInclude
#
#   Process an include file
    def Include (self, sFile):
        sInclude = self.FindInclude (sFile, self.sExt)
        if ( sInclude is None ):
            self.AsmErr ('Include file not found: ' + sFile)
            print ('Include file not found: ' + sFile)
            sys.exit (1)
        # print ('sInclude = ' + sInclude)
        self.ref.StartInclude (sInclude)
        self.AsmPass (sInclude)
        self.ref.EndInclude ()
#
#   Insert a binary file
    def Insert (self, sFile):
        sInsert = self.FindInclude (sFile, self.sExt)
        if ( sInsert is None ):
            self.AsmErr ('Insert file not found: ' + sFile)
            print ('Insert file not found: ' + sFile)
            sys.exit (1)
        with open (sInsert, 'rb') as fIns:
            while (True):
                b = fIns.read (256)
                if (( b is None ) or ( len (b) == 0 )):
                    break
                self.Code (b)
#
#   Process build number
    def GetBuild (self):
        sDir, sBuild = os.path.split (self.sBaseName)
        if ( self.style == 'MA' ):
            nCh = sBuild.find (',')
        else:
            nCh = sBuild.find ('.')
        if ( nCh > 0 ):
            sBuild = sBuild[0:nCh]
        sBuild = os.path.join (sDir, sBuild + '-build')
        sFile = self.FindFile (sBuild, '')
        if ( sFile is None ):
            # print ('No build file found. Using: ' + sBuild)
            self.fBuild = open (sBuild, 'w+b')
        else:
            # print ('Using build file: ' + sFile)
            self.fBuild = open (sFile, 'r+b')
        try:
            byBuild = self.fBuild.read (4)
            self.build = struct.unpack ('I', byBuild)[0]
        except IOError:
            self.build = 0
        except struct.error:
            self.build = 0
        self.build += 1

    def SaveBuild (self):
        if ( self.build is not None ):
            try:
                byBuild = struct.pack ('I', self.build)
            except struct.error:
                return
            try:
                self.fBuild.seek (0)
                self.fBuild.write (byBuild)
            except IOError:
                pass
            self.fBuild.close ()
#
#   Add build number
    def AddBuild (self, sFile, bAdd):
        if ( bAdd and sFile ):
            if ( self.build is None ):
                self.GetBuild ()
            sBuild = '_B{:d}'.format (self.build)
            nCh = sFile.rfind ('.')
            if ( nCh < 0 ):
                sFile += sBuild
            else:
                sFile = sFile[0:nCh] + sBuild + sFile[nCh:]
        return sFile
#
#   List file header
    def ListHead (self, args):
        if ( self.fList ):
            if ( args.modeline ):
                self.fList.write ('-*- mode: Fundamental; tab-width: 8; -*-\n')
            self.fList.write (' '.join (sys.argv) + '\n')
            self.fList.write ('In directory {:s}\n'.format (os.getcwd ()))
            self.fList.write ('Pass {:d} At {:s}\n\n'
                              .format (self.phase, time.strftime ('%H:%M on %d %b %Y')))
#
#   Assemble a source file
    def Assemble (self, args):
        self.sBaseName = args.source[0]
        args.binary = self.AddBuild (args.binary, args.number_build)
        args.hex = self.AddBuild (args.hex, args.number_build)
        self.cpu_type = args.cpu_type
        self.style = args.style
        self.bStrict = ( not args.permissive ) and ( not self.style in ['MA'] )
        self.lOrgUpd = []
        self.bUpdate = False
        if ( args.update is not None ):
            for sUpd in args.update:
                # print ('Update option: ' + sUpd)
                self.lOrgUpd.append (sUpd)
                if ( sUpd == 'ALL' ):
                    self.lOrgUpd = ['ORG', 'BORG', 'OFFSET', 'PHASE', 'DEPHASE', 'LOAD']
                    self.bUpdate = True
        self.bLabCase = ( self.style in ['M80'] )
        self.bDebug = args.debug
        self.inc_dirs = args.include
        self.bEcho = args.echo
        self.bAddress = args.address
        if ( args.cseg is not None ):
            self.base['C'] = args.cseg
        if ( args.dseg is not None ):
            self.base['D'] = args.dseg
        self.ref = Reformat (self, args.reformat, args.multi_inc)
        self.sExt = ''
        if ( self.style == 'MA' ):
            nCh = args.source[0].rfind (',')
            if ( nCh > 0 ):
                type = 0
                for ch in args.source[0][nCh+1:]:
                    if (( ch >= '0' ) and ( ch <= '9' )):
                        type = 10 * type + ord (ch) - ord ('0')
                    else:
                        type = 0
                        break
                if (( type >= 80 ) and ( type < 90 )):
                    self.eval = 1
        else:
            for i in range (len (args.source)):
                nCh = args.source[i].rfind ('.')
                if ( nCh >= 0 ):
                    self.sExt = args.source[i][nCh:]
                else:
                    if ( self.sExt == '' ):
                        if ( self.style == 'M80' ):
                            self.sExt = '.mac'
                        elif ( self.style == 'ZASM' ):
                            self.sExt = '.z80'
                        elif ( self.style == 'PASMO' ):
                            self.sExt = '.zsm'
                    args.source[i] += self.sExt
        self.bListForce = args.list_force
        self.bListCond = args.list_cond
        print ('Assembling Z80 source file(s) {:s} in style {:s}'.format (' '.join (args.source), args.style))
        if ( args.binary ):
            print ('   to binary file {:s}'.format (args.binary))
        if ( args.hex ):
            print ('   to hex file {:s}'.format (args.hex))
        if ( args.symbol ):
            print ('   to symbol file {:s}'.format (args.symbol))
        if ( args.list ):
            print ('   to list file {:s}'.format (args.list))
        if ( args.output ):
            print ('   to source file {:s} in style {:s}'.format (args.output, args.reformat))
        if ( self.eval > 0 ):
            print ('   using strictly left to right evaluator')
        if ( args.define is not None ):
            for equ in args.define:
                nEq = equ.find ('=')
                if ( nEq > 0 ):
                    name = equ[0:nEq]
                    val = int (equ[nEq+1:], 0)
                else:
                    name = equ
                    val = 1
                self.Label (name, True, val)
        print ('Starting pass one ...')
        tStart = time.time ()
        self.phase = 1
        self.nErr = 0
        if ( args.list ):
            self.fList = open (args.list, 'w')
            self.bList[True] = True
            self.bList[False] = args.list_cond
            self.ListHead (args)
        self.enable.append (True)
        for iSource, sSource in enumerate (args.source):
            self.locals[iSource] = {}
            self.labels = self.locals[iSource]
            self.AsmPass (sSource)
        print ('... completed pass one with {:d} error(s)'.format (self.nErr))
        if ( self.nErr > 0 ):
            if ( self.fList ):
                self.fList.write ('\n{:d} error(s) in pass one.\n'.format (self.nErr));
                self.fList.close ()
            sys.exit (1)
        print ('Starting pass two ...')
        self.phase = 2
        self.pc = {'A': 0, 'C': 0, 'D': 0}
        self.lc = {'A': 0, 'C': 0, 'D': 0}
        self.offset = 0
        if ( self.fList ):
            if ( args.keep ):
                self.fList.close ()
                if ( os.path.exists (args.keep) ):
                    os.remove (args.keep)
                os.rename (args.list, args.keep)
                self.fList = open (args.list, 'w')
            else:
                self.fList.seek (0)
            self.ListHead (args)
        if ( args.binary ):
            self.binout = BinOut (args.binary, args.fill)
        if ( args.hex ):
            self.hexout = HexOut (args.hex)
        if ( args.output ):
            self.ref.Open (args.output)
        if ( args.dseg is None ):
            self.base['D'] = self.lc['C']
        for iSource, sSource in enumerate (args.source):
            if ( ( args.output ) and ( args.modeline ) ):
                self.ref.CmntLine ('; -*- mode: Fundamental; tab-width: 8; -*-')
            self.ref.CmntLine ('; Converted to style {:s} from {:s} in style {:s}'
                               .format (args.reformat, sSource, args.style))
            self.ref.OpCode ('EVAL')
            if ( self.eval == 1 ):
                self.ref.AddArg ('SIMPLE')
            else:
                self.ref.AddArg ('FULL')
            self.ref.Output ()
            self.ref.OpCode ('LABCASE')
            if ( self.bLabCase ):
                self.ref.AddArg ('YES')
            else:
                self.ref.AddArg ('NO')
            self.ref.Output ()
            self.labels = self.locals[iSource]
            self.AsmPass (sSource)
        print ('... completed pass two with {:d} error(s)'.format (self.nErr))
        if ( self.hexout ):
            self.hexout.Close (self.begin, self.nErr > 0)
        if ( self.binout ):
            self.binout.Close (self.nErr > 0)
        if ( args.symbol and ( self.nErr == 0 )):
            self.SaveSymbols (args)
        tAssemble = time.time () - tStart
        if ( self.fList ):
            self.fList.write ('\n{:d} error(s) in pass two.\n'.format (self.nErr));
            self.fList.write ('Assembly completed in {:3.1f} sec.'.format (tAssemble))
            self.fList.close ()
        if ( args.output ):
            self.ref.Close (self.nErr > 0)
        if ( self.nErr > 0 ):
            sys.exit (1)
        elif (( self.build is not None ) and ( self.nErr == 0 )):
            self.SaveBuild ()
            print ('Build {:d} successfully completed.'.format (self.build))
        print ('Assembly completed in {:3.1f} sec.'.format (tAssemble))
#
    def SymbolTable (self, fSym, labels):
        names = list (labels.keys ())
        names.sort ()
        for n in names:
            if ( not n.startswith ('$') ):
                sym = labels[n]
                if ( self.style == 'ZASM' ):
                    sHex = '#{:X}'.format (sym.value)
                elif ( self.style == 'MA' ):
                    sHex = '${:X}'.format (sym.value)
                else:
                    sHex = '{:X}h'.format (sym.value)
                    if ( sHex[0] >= 'A' ):
                        sHex = '0' + sHex
                fSym.write ('{:16s}equ\t{:s}\t; {:s} {:s}:{:d}\n'
                            .format (sym.name + ':', sHex, sym.seg, sym.file, sym.line))
#
    def SaveSymbols (self, args):
        with open (args.symbol, 'w') as fSym:
            if ( args.modeline ):
                fSym.write ('; -*- mode: Fundamental; tab-width: 8; -*-\n')
            if ( self.publics ):
                fSym.write (';\n; Global symbols\n;\n')
                self.SymbolTable (fSym, self.publics)
            for iSource, sSource in enumerate (args.source):
                if ( self.locals[iSource] ):
                    fSym.write (';\n; Local symbols from {:s}\n;\n'.format (sSource))
                    self.SymbolTable (fSym, self.locals[iSource])
#
    def __init__ (self, args):
        self.lseg = 'A'
        self.pseg = 'A'
        self.base = {'A': 0, 'C': 0, 'D': 0}
        self.pc = {'A': 0, 'C': 0, 'D': 0}
        self.lc = {'A': 0, 'C': 0, 'D': 0}
        self.offset = 0
        self.locals = {}
        self.publics = {}
        self.files = []
        self.handles = []
        self.enable = []
        self.fList = None
        self.bList = {False: False, True: False}
        self.bSkipList = False
        self.binout = None
        self.hexout = None
        self.nErr = 0
        self.build = None
        self.chComment = None
        self.bPrintX = False
        self.begin = 0
        self.eval = 0
        self.macros = []
        self.Assemble (args)
#
def DefaultName (sFile, sSource, sExt):
    if ( sFile == '?' ):
        nCh = FindChar (sSource, '.,')
        if ( nCh < 0 ):
            nCh = len (sSource)
        return sSource[0:nCh] + sExt
    return sFile
#
def Run ():
    if ( len (sys.argv) == 1 ):
        sys.argv.append ('-h')
    parser = argparse.ArgumentParser (description = 'Assemble Z80 code written in different styles')
    parser.add_argument ('-v', '--version', action = 'version', version = '%(prog)s v231204')
    parser.add_argument ('-b', '--binary', help = 'Machine code in binary format',
                         nargs = '?', default = None, const = '?')
    parser.add_argument ('-f', '--fill', help = 'Fill byte for undefined addresses',
                         type=IntVal, default = 0xFF)
    parser.add_argument ('-x', '--hex', help = 'Machine code in Intel hex format',
                         nargs = '?', default = None, const = '?')
    parser.add_argument ('-y', '--symbol', help = 'Save all symbol definitions in source format',
                         nargs = '?', default = None, const = '?')
    parser.add_argument ('-n', '--number-build', help = 'Append build number to assembled file names',
                         action = 'store_true')
    parser.add_argument ('-l', '--list', help = 'List file',
                         nargs = '?', default = None, const = '?')
    parser.add_argument ('--list-force', help = 'Ignore NOLIST directives', action = 'store_true')
    parser.add_argument ('--list-cond', help = 'List false conditional code', action = 'store_true')
    parser.add_argument ('-a', '--address', help = 'Show load address as well as relocation',
                         action = 'store_true')
    parser.add_argument ('-o', '--output', help = 'Reformatted source file',
                         nargs = '?', default = None, const = '?')
    parser.add_argument ('-r', '--reformat', help = 'Style for reformatted source (default M80)',
                         choices = ('MA', 'M80', 'ZASM'), default = None) 
    parser.add_argument ('--multi-inc', help = 'Include files multiple times in reformatted source',
                         action = 'store_true')
    parser.add_argument ('-m', '--modeline', help = 'Emacs modeline in reformatted source',
                         action = 'store_true')
    parser.add_argument ('-k', '--keep', help = 'Keep pass 1 list file',
                         nargs = '?', default = None, const='?')
    parser.add_argument ('-e', '--echo', help = 'Echo source to screen',
                         action = 'store_true')
    parser.add_argument ('-t', '--cpu-type', help = 'The processor type',
                         choices = ('8080', 'Z80', 'Z180'), default = 'Z80')
    parser.add_argument ('-s', '--style', help = 'The style of the Z80 source',
                         choices = ('MA', 'M80', 'PASMO', 'ZASM'), required = True)
    parser.add_argument ('-p', '--permissive', help = 'Ignore some syntax errors',
                         action = 'store_true')
    parser.add_argument ('-u', '--update', help = 'Allow updating (patching) of previous code',
                         action = 'append', nargs='?', const='ALL', type=str.upper,
                         choices=['ALL', 'ORG', 'BORG', 'OFFSET', 'PHASE', 'DEPHASE', 'LOAD'])
    parser.add_argument ('-c', '--cseg', help = 'Start address for code segment',
                         type = IntVal, default = None)
    parser.add_argument ('-d', '--dseg', help = 'Start address for data segment',
                         type = IntVal, default = None)
    parser.add_argument ('--debug', help = 'Show assembler debug info',
                         action = 'store_true')
    parser.add_argument ('-D', '--define', help = 'Define an assembler equate',
                         action = 'append')
    parser.add_argument ('source', nargs = '*', help = 'The Z80 source file(s)')
    parser.add_argument ('-I', '--include', help = 'Folder to search for include files', action='append')
    args = parser.parse_args ()
    args.binary = DefaultName (args.binary, args.source[0], '.bin')
    args.hex = DefaultName (args.hex, args.source[0], '.hex')
    args.symbol = DefaultName (args.symbol, args.source[0], '.sym')
    if ( args.binary ):
        args.list = DefaultName (args.list, args.binary, '.lst')
    else:
        args.list = DefaultName (args.list, args.source[0], '.lst')
    args.keep = DefaultName (args.keep, args.source[0], '_p1.lst')
    if ( args.reformat ):
        if ( not args.output ):
            args.output = '?'
    else:
        args.reformat = 'M80'
    args.output = DefaultName (args.output, args.source[0], '.' + args.reformat.lower ())
    Assembler (args)
#
Run ()
