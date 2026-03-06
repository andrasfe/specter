       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST37.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(2) VALUE 5.
       01 WS-B           PIC 9(2) VALUE 10.
       01 WS-C           PIC X(2) VALUE 'AB'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A > 0 AND WS-A < 10
               DISPLAY 'A-IN-RANGE'
           END-IF
           IF WS-A = 1 OR WS-A = 5 OR WS-A = 9
               DISPLAY 'A-IS-1-5-9'
           END-IF
           IF WS-A > 3 AND (WS-B = 10 OR WS-B = 20)
               DISPLAY 'COMPLEX-TRUE'
           END-IF
           STOP RUN.
