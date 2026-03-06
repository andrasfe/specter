       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST53.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 100.
       01 WS-B           PIC 9(4) VALUE 25.
       01 WS-C           PIC 9(4) VALUE 10.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SUBTRACT WS-B FROM WS-A
           DISPLAY 'A-AFTER:' WS-A
           SUBTRACT WS-C FROM WS-A GIVING WS-B
           DISPLAY 'B-GIVING:' WS-B
           DISPLAY 'A-UNCHANGED:' WS-A
           STOP RUN.
