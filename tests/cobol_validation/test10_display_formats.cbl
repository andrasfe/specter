       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST10.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A          PIC 9(4) VALUE 42.
       01 WS-B          PIC X(5) VALUE 'WORLD'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HELLO'
           DISPLAY 'NUM=' WS-A
           DISPLAY 'STR=' WS-B
           DISPLAY 'MULTI=' WS-A ',' WS-B
           DISPLAY 'LITERAL-123'
           STOP RUN.
