       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST02.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG       PIC X VALUE 'Y'.
       01 WS-NUM        PIC 9(4) VALUE 15.
       01 WS-RESULT     PIC X(20) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = 'Y'
               DISPLAY 'FLAG-IS-Y'
           ELSE
               DISPLAY 'FLAG-IS-NOT-Y'
           END-IF
           IF WS-NUM > 10
               DISPLAY 'NUM-GT-10'
           END-IF
           IF WS-NUM < 20
               DISPLAY 'NUM-LT-20'
           END-IF
           IF WS-NUM NOT = 0
               DISPLAY 'NUM-NOT-ZERO'
           END-IF
           STOP RUN.
