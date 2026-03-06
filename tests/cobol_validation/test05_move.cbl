       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST05.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A          PIC X(10) VALUE SPACES.
       01 WS-B          PIC X(10) VALUE SPACES.
       01 WS-NUM        PIC 9(4) VALUE 0.
       01 WS-FLAG       PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'HELLO' TO WS-A
           DISPLAY 'A:' WS-A
           MOVE WS-A TO WS-B
           DISPLAY 'B:' WS-B
           MOVE 42 TO WS-NUM
           DISPLAY 'NUM:' WS-NUM
           MOVE ZEROS TO WS-NUM
           DISPLAY 'ZEROS:' WS-NUM
           MOVE SPACES TO WS-A
           DISPLAY 'SPACES:' WS-A
           MOVE 'Y' TO WS-FLAG
           DISPLAY 'FLAG:' WS-FLAG
           STOP RUN.
