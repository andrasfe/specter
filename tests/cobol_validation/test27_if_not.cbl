       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST27.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC X(4) VALUE 'TEST'.
       01 WS-B           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF NOT WS-A = SPACES
               DISPLAY 'A-NOT-SPACES'
           END-IF
           IF NOT WS-B > 0
               DISPLAY 'B-NOT-GT-0'
           END-IF
           IF NOT (WS-A = 'X' OR WS-A = 'Y')
               DISPLAY 'A-NOT-X-OR-Y'
           END-IF
           STOP RUN.
