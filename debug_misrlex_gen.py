from src.generation.answer_generator import AnswerGenerator

gen = AnswerGenerator()
result = gen.answer(
    "Tell me about MisrLeX project",
    source_mode="uploads",
    upload_session_id="8f997a9671444a2ea2baf7c4f94ef946",
    debug=True,
)
print("Answer:", result["answer"])
print("Error:", result.get("error"))
