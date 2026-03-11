# Paragraph Catalog

4 paragraphs, 1 test cases

---

## ADD-ONE

### Example Input
| Variable | Value |
|----------|-------|
| WS-COUNTER | `1` |
| WS-I | `TEST` |
| WS-SUM | `TEST` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| WS-COUNTER | `1` | `104` |

---

## CALC-EXIT

### Example Input
| Variable | Value |
|----------|-------|
| WS-COUNTER | `1` |
| WS-I | `TEST` |
| WS-SUM | `TEST` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| WS-COUNTER | `1` | `104` |
| WS-I | `TEST` | `6` |
| WS-SUM | `TEST` | `15` |

---

## CALC-PARA

### Example Input
| Variable | Value |
|----------|-------|
| WS-COUNTER | `1` |
| WS-I | `TEST` |
| WS-SUM | `TEST` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| WS-COUNTER | `1` | `104` |

---

## MAIN-PARA

**Calls:** [ADD-ONE](#add-one), [CALC-EXIT](#calc-exit), [CALC-PARA](#calc-para)

### Example Input
| Variable | Value |
|----------|-------|
| WS-COUNTER | `1` |
| WS-I | `TEST` |
| WS-SUM | `TEST` |

### State Changes
| Variable | Before | After |
|----------|--------|-------|
| WS-I | `TEST` | `6` |
| WS-SUM | `TEST` | `15` |
