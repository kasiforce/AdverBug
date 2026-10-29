protected Byte _parseByte(JsonParser p, DeserializationContext ctxt)
        throws JacksonException
    {
        String text;

        switch (p.currentTokenId()) {
        case JsonTokenId.ID_STRING: // let's do implicit re-parse
            text = p.getString();
            break;
        case JsonTokenId.ID_NUMBER_FLOAT:
            final CoercionAction act = _checkFloatToIntCoercion(p, ctxt, _valueClass);
            if (act == CoercionAction.AsNull) {
                return (Byte) getNullValue(ctxt);
            }
            if (act == CoercionAction.AsEmpty) {
                return (Byte) getEmptyValue(ctxt);
            }
            // 11-Oct-2025, tatu: [databind#5240] Cumbersome as there is no
            //  `getValueAsByte()` that'd avoid checks. So need to work around.
            int i = p.getValueAsInt();
            if (!_byteOverflow(i)) {
                // Let's trigger overflow handling
                return p.getByteValue();
            }
            return (byte) i;
        case JsonTokenId.ID_NULL: // null fine for non-primitive
            return (Byte) getNullValue(ctxt);
        case JsonTokenId.ID_NUMBER_INT:
            return p.getByteValue();
        case JsonTokenId.ID_START_ARRAY:
            return (Byte) _deserializeFromArray(p, ctxt);
        // 29-Jun-2020, tatu: New! "Scalar from Object" (mostly for XML)
        case JsonTokenId.ID_START_OBJECT:
            text = ctxt.extractScalarFromObject(p, this, _valueClass);
            // 17-May-2025, tatu: [databind#4656] need to check for `null`
            if (text != null) {
                break;
            }
            // fall through
        default:
            return (Byte) ctxt.handleUnexpectedToken(getValueType(ctxt), p);
        }

        // Rest of the processing is for coercion from String
        final CoercionAction act = _checkFromStringCoercion(ctxt, text);
        if (act == CoercionAction.AsNull) {
            return (Byte) getNullValue(ctxt);
        }
        if (act == CoercionAction.AsEmpty) {
            return (Byte) getEmptyValue(ctxt);
        }
        text = text.trim();
        if (_checkTextualNull(ctxt, text)) {
            return (Byte) getNullValue(ctxt);
        }
        int value;
        try {
            value = NumberInput.parseInt(text);
        } catch (IllegalArgumentException iae) {
            return (Byte) ctxt.handleWeirdStringValue(_valueClass, text,
                    "not a valid Byte value");
        }
        // So far so good: but does it fit?
        // as per [JACKSON-804], allow range up to 255, inclusive
        if (_byteOverflow(value)) {
            return (Byte) ctxt.handleWeirdStringValue(_valueClass, text,
                    "overflow, value cannot be represented as 8-bit value");
            // fall-through for deferred fails
        }
        return Byte.valueOf((byte) value);
    }