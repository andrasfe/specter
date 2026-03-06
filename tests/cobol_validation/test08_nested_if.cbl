       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST08.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A          PIC 9(4) VALUE 10.
       01 WS-B          PIC 9(4) VALUE 20.
       01 WS-C          PIC 9(4) VALUE 30.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A < WS-B
               IF WS-B < WS-C
                   DISPLAY 'A<B<C'
               ELSE
                   DISPLAY 'A<B>=C'
               END-IF
           ELSE
               DISPLAY 'A>=B'
           END-IF
           IF WS-A = 10 AND WS-B = 20
               DISPLAY 'BOTH-MATCH'
           END-IF
           IF WS-A = 99 OR WS-B = 20
               DISPLAY 'OR-MATCH'
           END-IF
           STOP RUN.
