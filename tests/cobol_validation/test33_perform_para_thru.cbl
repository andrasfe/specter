       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST33.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAL         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM STEP-A THRU STEP-C
           DISPLAY 'RESULT:' WS-VAL
           STOP RUN.
       STEP-A.
           ADD 1 TO WS-VAL.
       STEP-B.
           ADD 10 TO WS-VAL.
       STEP-C.
           ADD 100 TO WS-VAL.
