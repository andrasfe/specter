       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST42.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC X(10) VALUE SPACES.
       01 WS-B           PIC X(10) VALUE SPACES.
       01 WS-N           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'HELLO' TO WS-A
           MOVE 99 TO WS-N
           MOVE ALL '*' TO WS-B
           DISPLAY 'A:' WS-A
           DISPLAY 'N:' WS-N
           DISPLAY 'B:' WS-B
           MOVE ZEROS TO WS-N
           MOVE SPACES TO WS-A
           DISPLAY 'N0:' WS-N
           DISPLAY 'ASPACE:' WS-A
           STOP RUN.
