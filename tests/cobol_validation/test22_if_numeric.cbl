       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST22.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM         PIC X(4) VALUE '1234'.
       01 WS-ALPHA       PIC X(4) VALUE 'ABCD'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-NUM IS NUMERIC
               DISPLAY 'NUM-IS-NUMERIC'
           END-IF
           IF WS-ALPHA IS NUMERIC
               DISPLAY 'ALPHA-IS-NUMERIC'
           ELSE
               DISPLAY 'ALPHA-NOT-NUMERIC'
           END-IF
           STOP RUN.
