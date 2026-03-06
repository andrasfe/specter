       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST21.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 10.
       01 WS-B           PIC 9(4) VALUE 20.
       01 WS-C           PIC 9(4) VALUE 30.
       01 WS-D           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD WS-A WS-B GIVING WS-D
           DISPLAY 'TWO-GIVING:' WS-D
           ADD WS-A WS-B WS-C GIVING WS-D
           DISPLAY 'THREE-GIVING:' WS-D
           ADD 5 WS-A GIVING WS-D
           DISPLAY 'LIT-VAR-GIVING:' WS-D
           STOP RUN.
