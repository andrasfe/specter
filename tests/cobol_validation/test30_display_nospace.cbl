       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST30.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 1.
       01 WS-B           PIC 9(4) VALUE 2.
       01 WS-C           PIC 9(4) VALUE 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-A WS-B WS-C
           DISPLAY 'X' WS-A 'Y' WS-B 'Z'
           STOP RUN.
