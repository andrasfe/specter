       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST44.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC S9(4) VALUE -5.
       01 WS-B           PIC S9(4) VALUE 10.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A < 0
               DISPLAY 'A-NEGATIVE'
           END-IF
           IF WS-A < WS-B
               DISPLAY 'A-LESS-THAN-B'
           END-IF
           ADD WS-A TO WS-B
           DISPLAY 'SUM:' WS-B
           STOP RUN.
