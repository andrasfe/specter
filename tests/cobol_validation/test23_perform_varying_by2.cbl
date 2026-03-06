       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST23.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I           PIC 9(4) VALUE 0.
       01 WS-COUNT       PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-I FROM 1 BY 2
               UNTIL WS-I > 10
               ADD 1 TO WS-COUNT
           END-PERFORM
           DISPLAY 'COUNT:' WS-COUNT
           DISPLAY 'FINAL-I:' WS-I
           STOP RUN.
