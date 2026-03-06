       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST13.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 100.
       01 WS-B           PIC 9(4) VALUE 30.
       01 WS-C           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SUBTRACT WS-B FROM WS-A
           DISPLAY 'SUB-FROM:' WS-A
           ADD WS-A TO WS-B
           DISPLAY 'ADD-TO:' WS-B
           ADD 10 20 GIVING WS-C
           DISPLAY 'ADD-GIVING:' WS-C
           STOP RUN.
