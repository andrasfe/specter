# Paragraph Catalog

43 paragraphs, 24 test cases

---

## 1000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 1000-INITIALIZE

**Calls:** [1100-EXIT](#1100-exit), [1100-OPEN-REQUEST-QUEUE](#1100-open-request-queue), [3100-EXIT](#3100-exit), [3100-READ-REQUEST-MQ](#3100-read-request-mq)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CRITICAL | `` | `00` |
| WS-WAIT-INTERVAL | `` | `5000` |

---

## 1100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 1100-OPEN-REQUEST-QUEUE

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |
| WS-COMPCODE | `` | `00` |
| WS-OPTIONS | `` | `0` |

---

## 1200-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 1200-SCHEDULE-PSB

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| IMS-PSB-SCHD | `` | `True` |
| IMS-RETURN-CODE | `0` | `` |
| PSB-SCHEDULED-MORE-THAN-ONCE | `` | `00` |
| STATUS-OK | `` | `00` |

---

## 2000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 2000-MAIN-PROCESS

**Calls:** [2100-EXIT](#2100-exit), [2100-EXTRACT-REQUEST-MSG](#2100-extract-request-msg), [3100-EXIT](#3100-exit), [3100-READ-REQUEST-MQ](#3100-read-request-mq), [5000-EXIT](#5000-exit), [5000-PROCESS-AUTH](#5000-process-auth)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CRITICAL | `` | `00` |
| IMS-PSB-NOT-SCHD | `` | `True` |
| WS-LOOP-END | `` | `True` |
| WS-MSG-PROCESSED | `` | `1` |

---

## 2100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 2100-EXTRACT-REQUEST-MSG

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| PA-RQ-ACQR-COUNTRY-CODE | `1` | `` |
| PA-RQ-AUTH-DATE | `250101` | `` |
| PA-RQ-AUTH-TIME | `120000` | `` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` | `` |
| PA-RQ-CARD-NUM | `10001` | `` |
| PA-RQ-MERCHANT-ID | `10001` | `` |
| PA-RQ-TRANSACTION-ID | `10001` | `` |
| WS-TRANSACTION-AMT-AN | `100` | `` |

---

## 3100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 3100-READ-REQUEST-MQ

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| MQGMO-OPTIONS | `` | `0` |
| MQGMO-WAITINTERVAL | `` | `5000` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |
| WS-COMPCODE | `` | `00` |

---

## 5000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5000-PROCESS-AUTH

**Calls:** [1200-EXIT](#1200-exit), [1200-SCHEDULE-PSB](#1200-schedule-psb), [5100-EXIT](#5100-exit), [5100-READ-XREF-RECORD](#5100-read-xref-record), [5200-EXIT](#5200-exit), [5200-READ-ACCT-RECORD](#5200-read-acct-record), [5300-EXIT](#5300-exit), [5300-READ-CUST-RECORD](#5300-read-cust-record), [5500-EXIT](#5500-exit), [5500-READ-AUTH-SUMMRY](#5500-read-auth-summry), [5600-EXIT](#5600-exit), [5600-READ-PROFILE-DATA](#5600-read-profile-data), [6000-EXIT](#6000-exit), [6000-MAKE-DECISION](#6000-make-decision), [7100-EXIT](#7100-exit), [7100-SEND-RESPONSE](#7100-send-response), [8000-EXIT](#8000-exit), [8000-WRITE-AUTH-TO-DB](#8000-write-auth-to-db)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| FOUND-ACCT-IN-MSTR | `` | `True` |

---

## 5100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5100-READ-XREF-RECORD

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |

---

## 5200-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5200-READ-ACCT-RECORD

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| WS-CARD-RID-ACCT-ID | `` | `10001` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |

---

## 5300-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5300-READ-CUST-RECORD

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| WS-CARD-RID-CUST-ID | `` | `10001` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |

---

## 5500-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5500-READ-AUTH-SUMMRY

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| FOUND-PAUT-SMRY-SEG | `` | `True` |
| IMS-RETURN-CODE | `0` | `` |
| PA-ACCT-ID | `` | `10001` |
| PSB-SCHEDULED-MORE-THAN-ONCE | `` | `00` |
| STATUS-OK | `` | `00` |

---

## 5600-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 5600-READ-PROFILE-DATA

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 6000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 6000-MAKE-DECISION

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| AUTH-RESP-APPROVED | `` | `True` |
| PA-RL-AUTH-ID-CODE | `0` | `` |
| PA-RL-AUTH-RESP-CODE | `0` | `00` |
| PA-RL-AUTH-RESP-REASON | `` | `0000` |
| W02-PUT-BUFFER | `` | `,,,00,0000,100,` |
| WS-APPROVED-AMT-DIS | `0` | `100` |

---

## 7100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 7100-SEND-RESPONSE

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-LOCATION | `` | `M004` |
| ERR-MQ | `` | `True` |
| MQMD-EXPIRY | `` | `50` |
| MQMD-REPLYTOQ | `` | ` ` |
| MQMD-REPLYTOQMGR | `` | ` ` |
| W02-BUFFLEN | `0` | `` |
| WS-CODE-DISPLAY | `0` | `__NOMATCH__` |
| WS-COMPCODE | `` | `00` |

---

## 8000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 8000-WRITE-AUTH-TO-DB

**Calls:** [8400-EXIT](#8400-exit), [8400-UPDATE-SUMMARY](#8400-update-summary), [8500-EXIT](#8500-exit), [8500-INSERT-AUTH](#8500-insert-auth)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 8400-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 8400-UPDATE-SUMMARY

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| IMS-RETURN-CODE | `0` | `` |
| PA-APPROVED-AUTH-AMT | `100` | `500` |
| PA-APPROVED-AUTH-CNT | `1` | `5` |
| PA-CASH-BALANCE | `` | `0` |
| PA-CREDIT-BALANCE | `` | `400` |
| PSB-SCHEDULED-MORE-THAN-ONCE | `` | `00` |
| STATUS-OK | `` | `00` |

---

## 8500-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 8500-INSERT-AUTH

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CRITICAL | `` | `00` |
| IMS-RETURN-CODE | `0` | `` |
| PA-ACCT-ID | `` | `10001` |
| PA-ACQR-COUNTRY-CODE | `0` | `` |
| PA-AUTH-DATE-9C | `0` | `74989` |
| PA-AUTH-FRAUD | `` | ` ` |
| PA-AUTH-ID-CODE | `0` | `` |
| PA-AUTH-ORIG-TIME | `0` | `` |
| PA-AUTH-RESP-CODE | `0` | `00` |
| PA-AUTH-RESP-REASON | `` | `0000` |
| PA-AUTH-TIME-9C | `0` | `999999999` |
| PA-CARD-NUM | `10001` | `` |
| PA-MATCH-PENDING | `` | `True` |
| PA-MERCHANT-CATAGORY-CODE | `0` | `` |
| PA-PROCESSING-CODE | `0` | `` |

---

## 9000-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 9000-TERMINATE

**Calls:** [9100-CLOSE-REQUEST-QUEUE](#9100-close-request-queue), [9100-EXIT](#9100-exit)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| PSB-SCHEDULED-MORE-THAN-ONCE | `` | `00` |
| STATUS-OK | `` | `00` |

---

## 9100-CLOSE-REQUEST-QUEUE

**Calls:** [9500-LOG-ERROR](#9500-log-error)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 9100-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 9500-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## 9500-LOG-ERROR

**Calls:** [9990-END-ROUTINE](#9990-end-routine)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-APPLICATION | `` | `10001` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-TIME | `0` | `120000` |

---

## 9990-END-ROUTINE

**Calls:** [9000-TERMINATE](#9000-terminate)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CRITICAL | `` | `00` |

---

## 9990-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| APPROVE-AUTH | `` | `True` |
| AUTH-RESP-APPROVED | `` | `True` |
| CARD-FOUND-XREF | `` | `True` |
| ERR-APPLICATION | `` | `10001` |
| ERR-CICS | `` | `True` |
| ERR-CODE-1 | `0` | `00` |
| ERR-CODE-2 | `0` | `__NOMATCH__` |
| ERR-CRITICAL | `` | `00` |
| ERR-DATE | `` | `250101` |
| ERR-LOCATION | `` | `M004` |
| ERR-MESSAGE | `` | `REQ MQ OPEN ERROR` |
| ERR-MQ | `` | `True` |
| ERR-TIME | `0` | `120000` |
| FOUND-ACCT-IN-MSTR | `` | `True` |
| FOUND-PAUT-SMRY-SEG | `` | `True` |

---

## MAIN-PARA

**Calls:** [1000-EXIT](#1000-exit), [1000-INITIALIZE](#1000-initialize), [2000-EXIT](#2000-exit), [2000-MAIN-PROCESS](#2000-main-process), [9000-EXIT](#9000-exit), [9000-TERMINATE](#9000-terminate)

### Example Input
| Variable | Value |
|----------|-------|
| DFHRESP | `0` |
| EIBRESP | `0` |
| MQRC-NO-MSG-AVAILABLE | `__NOMATCH___DIFF` |
| NO-MORE-MSG-AVAILABLE | `False` |
| NUMVAL | `10001` |
| PA-APPROVED-AUTH-AMT | `100` |
| PA-APPROVED-AUTH-CNT | `1` |
| PA-CARD-NUM | `10001` |
| PA-DECLINED-AUTH-AMT | `100` |
| PA-DECLINED-AUTH-CNT | `1` |
| PA-RQ-ACQR-COUNTRY-CODE | `1` |
| PA-RQ-AUTH-DATE | `250101` |
| PA-RQ-AUTH-TIME | `120000` |
| PA-RQ-CARD-EXPIRY-DATE | `250101` |
| PA-RQ-CARD-NUM | `10001` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| ERR-CRITICAL | `` | `00` |
