       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST11.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TABLE.
           05 WS-ITEM OCCURS 5 TIMES PIC 9(2).
       01 WS-IDX         PIC 9(4) VALUE 1.
       01 WS-FOUND        PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 10 TO WS-ITEM(1)
           MOVE 20 TO WS-ITEM(2)
           MOVE 30 TO WS-ITEM(3)
           MOVE 40 TO WS-ITEM(4)
           MOVE 50 TO WS-ITEM(5)
           DISPLAY 'TABLE-LOADED'
           DISPLAY 'DONE'
           STOP RUN.
