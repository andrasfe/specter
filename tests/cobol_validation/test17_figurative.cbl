       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST17.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC X(10) VALUE 'HELLO'.
       01 WS-NUM         PIC 9(4) VALUE 42.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A NOT = SPACES
               DISPLAY 'NOT-SPACES'
           END-IF
           MOVE SPACES TO WS-A
           IF WS-A = SPACES
               DISPLAY 'IS-SPACES'
           END-IF
           IF WS-NUM NOT = ZEROS
               DISPLAY 'NOT-ZEROS'
           END-IF
           MOVE ZEROS TO WS-NUM
           IF WS-NUM = ZEROS
               DISPLAY 'IS-ZEROS'
           END-IF
           STOP RUN.
