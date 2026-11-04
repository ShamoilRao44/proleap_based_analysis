package local.cobol.facts;

import java.io.IOException;
import java.io.StringWriter;
import java.io.Writer;
import java.util.Collection;
import java.util.Map;

/** Minimal JSON serializer for Map / List / String / Number / Boolean / null. */
public class Json {

	public static String write(final Object value) {
		final StringWriter out = new StringWriter();
		try {
			write(value, out);
		} catch (final IOException e) {
			throw new IllegalStateException(e);
		}
		return out.toString();
	}

	public static void write(final Object value, final Writer out) throws IOException {
		if (value == null) {
			out.write("null");
		} else if (value instanceof Boolean) {
			out.write(value.toString());
		} else if (value instanceof Double || value instanceof Float) {
			final double d = ((Number) value).doubleValue();
			out.write(Double.isNaN(d) || Double.isInfinite(d) ? "null" : value.toString());
		} else if (value instanceof Number) {
			out.write(value.toString());
		} else if (value instanceof String) {
			string((String) value, out);
		} else if (value instanceof Map) {
			out.write('{');
			boolean first = true;
			for (final Map.Entry<?, ?> e : ((Map<?, ?>) value).entrySet()) {
				if (!first) {
					out.write(',');
				}
				first = false;
				string(String.valueOf(e.getKey()), out);
				out.write(':');
				write(e.getValue(), out);
			}
			out.write('}');
		} else if (value instanceof Collection) {
			out.write('[');
			boolean first = true;
			for (final Object o : (Collection<?>) value) {
				if (!first) {
					out.write(',');
				}
				first = false;
				write(o, out);
			}
			out.write(']');
		} else {
			string(String.valueOf(value), out);
		}
	}

	protected static void string(final String s, final Writer out) throws IOException {
		out.write('"');
		for (int i = 0; i < s.length(); i++) {
			final char c = s.charAt(i);
			switch (c) {
			case '"':
				out.write("\\\"");
				break;
			case '\\':
				out.write("\\\\");
				break;
			case '\n':
				out.write("\\n");
				break;
			case '\r':
				out.write("\\r");
				break;
			case '\t':
				out.write("\\t");
				break;
			case '\b':
				out.write("\\b");
				break;
			case '\f':
				out.write("\\f");
				break;
			default:
				if (c < 0x20) {
					out.write(String.format("\\u%04x", (int) c));
				} else {
					out.write(c);
				}
			}
		}
		out.write('"');
	}
}
