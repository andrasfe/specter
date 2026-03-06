       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST03.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE       PIC 9(2) VALUE 2.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-CODE
               WHEN 1
                   DISPLAY 'CODE-IS-1'
               WHEN 2
                   DISPLAY 'CODE-IS-2'
               WHEN 3
                   DISPLAY 'CODE-IS-3'
               WHEN OTHER
                   DISPLAY 'CODE-IS-OTHER'
           END-EVALUATE
           EVALUATE TRUE
               WHEN WS-CODE > 5
                   DISPLAY 'GT-5'
               WHEN WS-CODE > 0
                   DISPLAY 'GT-0'
               WHEN OTHER
                   DISPLAY 'LE-0'
           END-EVALUATE
           STOP RUN.
