       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST39.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I           PIC 9(4) VALUE 0.
       01 WS-SUM         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-I FROM 5 BY -1
               UNTIL WS-I < 1
               ADD WS-I TO WS-SUM
           END-PERFORM
           DISPLAY 'SUM-DOWN:' WS-SUM
           STOP RUN.
