       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST52.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 10.
       01 WS-B           PIC 9(4) VALUE 20.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A IS GREATER THAN WS-B
               DISPLAY 'A-GREATER'
           ELSE
               DISPLAY 'A-NOT-GREATER'
           END-IF
           IF WS-A IS LESS THAN WS-B
               DISPLAY 'A-LESS'
           ELSE
               DISPLAY 'A-NOT-LESS'
           END-IF
           IF WS-A IS EQUAL TO WS-B
               DISPLAY 'EQUAL'
           ELSE
               DISPLAY 'NOT-EQUAL'
           END-IF
           STOP RUN.
