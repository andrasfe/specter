       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST50.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 0.
       01 WS-B           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 100 / 3
           COMPUTE WS-B ROUNDED = 100 / 3
           DISPLAY 'TRUNC:' WS-A
           DISPLAY 'ROUND:' WS-B
           STOP RUN.
