       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST32.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG        PIC X VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = 'Y'
               DISPLAY 'BEFORE-GOBACK'
               GOBACK
           END-IF
           DISPLAY 'SHOULD-NOT-REACH'
           STOP RUN.
