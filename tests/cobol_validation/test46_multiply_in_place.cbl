       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST46.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 5.
       01 WS-B           PIC 9(4) VALUE 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MULTIPLY WS-A BY WS-B
           DISPLAY 'B:' WS-B
           DISPLAY 'A:' WS-A
           STOP RUN.
