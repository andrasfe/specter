       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST07.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STEP       PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'START'
           GO TO STEP-ONE.
       STEP-ONE.
           ADD 1 TO WS-STEP
           DISPLAY 'STEP:' WS-STEP
           IF WS-STEP < 3
               GO TO STEP-ONE
           END-IF
           DISPLAY 'DONE'
           STOP RUN.
