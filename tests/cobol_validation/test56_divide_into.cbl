       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST56.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 100.
       01 WS-B           PIC 9(4) VALUE 3.
       01 WS-Q           PIC 9(4) VALUE 0.
       01 WS-R           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DIVIDE WS-B INTO WS-A GIVING WS-Q REMAINDER WS-R
           DISPLAY 'Q:' WS-Q
           DISPLAY 'R:' WS-R
           DISPLAY 'A:' WS-A
           STOP RUN.
