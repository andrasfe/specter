       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST48.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 10.
       01 WS-B           PIC 9(4) VALUE 20.
       01 WS-C           PIC 9(4) VALUE 30.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD WS-A WS-B TO WS-C
           DISPLAY 'C:' WS-C
           STOP RUN.
