       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST12.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 10.
       01 WS-B           PIC 9(4) VALUE 3.
       01 WS-C           PIC 9(8) VALUE 0.
       01 WS-D           PIC 9(8) VALUE 0.
       01 WS-E           PIC 9(8) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-C = WS-A * WS-B
           DISPLAY 'MUL:' WS-C
           COMPUTE WS-D = WS-A + WS-B * 2
           DISPLAY 'EXPR:' WS-D
           COMPUTE WS-E = (WS-A + WS-B) * 2
           DISPLAY 'PAREN:' WS-E
           STOP RUN.
