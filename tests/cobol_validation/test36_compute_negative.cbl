       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST36.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC S9(4) VALUE 10.
       01 WS-B           PIC S9(4) VALUE 25.
       01 WS-C           PIC S9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-C = WS-A - WS-B
           DISPLAY 'NEG:' WS-C
           COMPUTE WS-C = WS-B - WS-A
           DISPLAY 'POS:' WS-C
           STOP RUN.
