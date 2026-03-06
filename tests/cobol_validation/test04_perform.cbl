       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST04.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNTER    PIC 9(4) VALUE 0.
       01 WS-SUM        PIC 9(4) VALUE 0.
       01 WS-I          PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM ADD-ONE 3 TIMES
           DISPLAY 'COUNTER:' WS-COUNTER
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > 5
               ADD WS-I TO WS-SUM
           END-PERFORM
           DISPLAY 'SUM:' WS-SUM
           PERFORM CALC-PARA THRU CALC-EXIT
           DISPLAY 'AFTER-THRU:' WS-COUNTER
           STOP RUN.
       ADD-ONE.
           ADD 1 TO WS-COUNTER.
       CALC-PARA.
           ADD 100 TO WS-COUNTER.
       CALC-EXIT.
           EXIT.
