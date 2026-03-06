       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST41.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SCORE       PIC 9(3) VALUE 75.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE TRUE
               WHEN WS-SCORE >= 90
                   DISPLAY 'GRADE-A'
               WHEN WS-SCORE >= 80
                   DISPLAY 'GRADE-B'
               WHEN WS-SCORE >= 70
                   DISPLAY 'GRADE-C'
               WHEN WS-SCORE >= 60
                   DISPLAY 'GRADE-D'
               WHEN OTHER
                   DISPLAY 'GRADE-F'
           END-EVALUATE
           STOP RUN.
