       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST34.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS      PIC X(2) VALUE '00'.
       01 WS-COUNT       PIC 9(4) VALUE 5.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-STATUS = '00'
               DISPLAY 'STATUS-OK'
           END-IF
           IF WS-STATUS NOT = '00'
               DISPLAY 'STATUS-NOT-OK'
           END-IF
           IF WS-COUNT >= 5
               DISPLAY 'COUNT-GE-5'
           END-IF
           IF WS-COUNT <= 5
               DISPLAY 'COUNT-LE-5'
           END-IF
           STOP RUN.
