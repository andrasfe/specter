       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST57.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 5.
       01 WS-B           PIC 9(4) VALUE 10.
       01 WS-C           PIC 9(4) VALUE 15.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A < WS-B AND WS-B < WS-C
               DISPLAY 'ASCENDING'
           END-IF
           IF WS-A > WS-B OR WS-B > WS-C
               DISPLAY 'NOT-ASCENDING'
           ELSE
               DISPLAY 'CONFIRMED-ASC'
           END-IF
           IF NOT WS-A = WS-B
               DISPLAY 'NOT-EQUAL'
           END-IF
           STOP RUN.
