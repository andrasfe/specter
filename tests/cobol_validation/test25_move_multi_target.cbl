       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST25.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 0.
       01 WS-B           PIC 9(4) VALUE 0.
       01 WS-C           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 42 TO WS-A WS-B WS-C
           DISPLAY 'A:' WS-A
           DISPLAY 'B:' WS-B
           DISPLAY 'C:' WS-C
           STOP RUN.
