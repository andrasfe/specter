       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST20.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-YEAR        PIC 9(4) VALUE 2024.
       01 WS-Q           PIC 9(4) VALUE 0.
       01 WS-R           PIC 9(4) VALUE 0.
       01 WS-A           PIC 9(4) VALUE 17.
       01 WS-B           PIC 9(4) VALUE 5.
       01 WS-C           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DIVIDE WS-YEAR BY 4 GIVING WS-Q
             REMAINDER WS-R
           DISPLAY 'YEAR-Q:' WS-Q
           DISPLAY 'YEAR-R:' WS-R
           DIVIDE WS-A BY WS-B GIVING WS-C
             REMAINDER WS-R
           DISPLAY 'DIV-C:' WS-C
           DISPLAY 'DIV-R:' WS-R
           STOP RUN.
