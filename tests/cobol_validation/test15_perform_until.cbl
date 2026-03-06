       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST15.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I           PIC 9(4) VALUE 0.
       01 WS-SUM         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-I >= 5
               ADD 1 TO WS-I
               ADD WS-I TO WS-SUM
           END-PERFORM
           DISPLAY 'LOOP-SUM:' WS-SUM
           DISPLAY 'LOOP-I:' WS-I
           STOP RUN.
