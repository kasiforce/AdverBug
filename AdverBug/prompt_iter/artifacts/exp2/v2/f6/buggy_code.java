@Override
    public YearMonth deserialize(JsonParser p, DeserializationContext ctxt) throws JacksonException
    {
        if (p.hasToken(JsonToken.VALUE_STRING)) {
            return _fromString(p, ctxt, p.getString());
        }
        // 30-Sep-2020, tatu: New! "Scalar from Object" (mostly for XML)
        if (p.isExpectedStartObjectToken()) {
            final String str = ctxt.extractScalarFromObject(p, this, handledType());
            // 17-May-2025, tatu: [databind#4656] need to check for `null`
            if (str != null) {
                return _fromString(p, ctxt, str);
            }
            // fall through
        } else if (p.isExpectedStartArrayToken()) {
            JsonToken t = p.nextToken();
            if (t == JsonToken.END_ARRAY) {
                return null;
            }
            if ((t == JsonToken.VALUE_STRING || t == JsonToken.VALUE_EMBEDDED_OBJECT)
                    && ctxt.isEnabled(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)) {
                final YearMonth parsed = deserialize(p, ctxt);
                if (p.nextToken() != JsonToken.END_ARRAY) {
                    handleMissingEndArrayForSingle(p, ctxt);
                }
                return parsed;            
            }
            if (t != JsonToken.VALUE_NUMBER_INT) {
                _reportWrongToken(ctxt, JsonToken.VALUE_NUMBER_INT, "years");
            }
            int year = p.getIntValue();
            int month = p.nextIntValue(0);
            if (month == -1) {
                if (!p.hasToken(JsonToken.VALUE_NUMBER_INT)) {
                    _reportWrongToken(ctxt, JsonToken.VALUE_NUMBER_INT, "months");
                }
                month = p.getIntValue();
            }
            if (p.nextToken() != JsonToken.END_ARRAY) {
                throw ctxt.wrongTokenException(p, handledType(), JsonToken.END_ARRAY,
                        "Expected array to end");
            }
            try {
                return YearMonth.of(year, month);
            } catch (DateTimeException e) {
                throw DateTimeParseException.from(p,
                        "Failed to deserialize %s from array value [%d,%d]: %s".formatted(
                                handledType().getName(), year, month, e.getMessage()),
                        "[%d,%d]".formatted(year, month),
                        handledType(), e);
            }
        } else if (p.hasToken(JsonToken.VALUE_EMBEDDED_OBJECT)) {
            return (YearMonth) p.getEmbeddedObject();
        }
        return _handleUnexpectedToken(ctxt, p,
                JsonToken.VALUE_STRING, JsonToken.START_ARRAY);
    }