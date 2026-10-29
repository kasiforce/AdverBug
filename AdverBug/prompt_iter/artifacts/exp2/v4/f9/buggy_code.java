@Override
    public String[] deserialize(JsonParser p, DeserializationContext ctxt,
            String[] intoValue) throws JacksonException
    {
        // Ok: must point to START_ARRAY (or equivalent)
        if (!p.isExpectedStartArrayToken()) {
            String[] arr = handleNonArray(p, ctxt);
            if (arr == null) {
                return intoValue;
            }
            final int offset = intoValue.length;
            String[] result = Arrays.copyOf(intoValue, offset + arr.length);
            System.arraycopy(arr, 0, result, offset, arr.length);
            return result;
        }

        if (_elementDeserializer != null) {
            return _deserializeCustom(p, ctxt, intoValue);
        }
        final ObjectBuffer buffer = ctxt.leaseObjectBuffer();
        int ix = intoValue.length;
        Object[] chunk = buffer.resetAndStart(intoValue, ix);

        try {
            while (true) {
                String value = p.nextStringValue();
                if (value == null) {
                    JsonToken t = p.currentToken();
                    if (t == JsonToken.END_ARRAY) {
                        break;
                    }
                    if (t == JsonToken.VALUE_NULL) {
                        // 03-Feb-2017, tatu: Should we skip null here or not?
                        value = null;
                    } else {
                        value = _parseString(p, ctxt, _nullProvider);
                    }

                    if (value == null) {
                        value = (String) _nullProvider.getNullValue(ctxt);

                        if (value != null && _skipNullValues) {
                            continue;
                        }
                    }
                }
                if (ix >= chunk.length) {
                    chunk = buffer.appendCompletedChunk(chunk);
                    ix = 0;
                }
                chunk[ix++] = value;
            }
        } catch (Exception e) {
            throw DatabindException.wrapWithPath(ctxt, e,
                    new JacksonException.Reference(chunk, buffer.bufferedSize() + ix));
        }
        String[] result = buffer.completeAndClearBuffer(chunk, ix, String.class);
        ctxt.returnObjectBuffer(buffer);
        return result;
    }