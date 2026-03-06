       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST01.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A          PIC 9(4) VALUE 10.
       01 WS-B          PIC 9(4) VALUE 20.
       01 WS-C          PIC 9(4) VALUE 0.
       01 WS-D          PIC 9(4) VALUE 100.
       01 WS-E          PIC 9(4) VALUE 0.
       01 WS-REM        PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD WS-A TO WS-B
           DISPLAY 'ADD-TO:' WS-B
           SUBTRACT 5 FROM WS-B
           DISPLAY 'SUB:' WS-B
           MULTIPLY WS-A BY WS-D
           DISPLAY 'MUL:' WS-D
           DIVIDE WS-D BY WS-A GIVING WS-E
             REMAINDER WS-REM
           DISPLAY 'DIV:' WS-E
           DISPLAY 'REM:' WS-REM
           COMPUTE WS-C = WS-A + 5
           DISPLAY 'COMPUTE:' WS-C
           STOP RUN.
