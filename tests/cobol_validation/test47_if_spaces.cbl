       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST47.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME        PIC X(10) VALUE SPACES.
       01 WS-CODE        PIC X(5) VALUE 'HELLO'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-NAME = SPACES
               DISPLAY 'NAME-EMPTY'
           ELSE
               DISPLAY 'NAME-SET'
           END-IF
           IF WS-CODE = SPACES
               DISPLAY 'CODE-EMPTY'
           ELSE
               DISPLAY 'CODE-SET'
           END-IF
           STOP RUN.
