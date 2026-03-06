       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST29.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 12.
       01 WS-B           PIC 9(4) VALUE 5.
       01 WS-C           PIC 9(8) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MULTIPLY WS-A BY WS-B GIVING WS-C
           DISPLAY 'MUL-GIVING:' WS-C
           DISPLAY 'A-SAME:' WS-A
           DISPLAY 'B-SAME:' WS-B
           STOP RUN.
