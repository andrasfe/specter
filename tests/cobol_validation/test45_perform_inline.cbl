       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST45.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I           PIC 9(4) VALUE 0.
       01 WS-SUM         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > 5
               ADD WS-I TO WS-SUM
           END-PERFORM
           DISPLAY 'SUM:' WS-SUM
           STOP RUN.
