       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST54.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS      PIC X(2) VALUE 'OK'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-STATUS
               WHEN 'OK'
                   DISPLAY 'STATUS-OK'
               WHEN 'ER'
                   DISPLAY 'STATUS-ERROR'
               WHEN OTHER
                   DISPLAY 'STATUS-UNKNOWN'
           END-EVALUATE
           STOP RUN.
