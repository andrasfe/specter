       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST38.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 10.
       01 WS-B           PIC 9(4) VALUE 20.
       01 WS-C           PIC 9(4) VALUE 30.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 5 TO WS-A
           ADD 5 TO WS-B
           ADD 5 TO WS-C
           DISPLAY 'A:' WS-A
           DISPLAY 'B:' WS-B
           DISPLAY 'C:' WS-C
           SUBTRACT 3 FROM WS-A
           SUBTRACT 3 FROM WS-B
           DISPLAY 'A2:' WS-A
           DISPLAY 'B2:' WS-B
           STOP RUN.
