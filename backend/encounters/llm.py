import os
from openai import OpenAI
from .models import Encounter, NoteTemplate
import json
from pathlib import Path

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def call_llm(encounter_id, template_id):
    encounter = Encounter.objects.select_related(
        "patient",
        "provider",
    ).get(id=encounter_id)

    template = NoteTemplate.objects.get(id=template_id, is_active=True)

    patient = encounter.patient

    previous_encounters = (
        Encounter.objects
        .filter(patient=patient)
        .exclude(id=encounter.id)
        .order_by("updated_at")
    )

    previous_history_blocks = []

    for previous_encounter in previous_encounters:
        latest_final_note = (
            previous_encounter.versions
            .order_by("-saved_at")
            .first()
        )

        previous_history_blocks.append(
            f"""
                        Encounter ID: {previous_encounter.id}
                        Date Updated: {previous_encounter.updated_at}

                        Raw Input:
                        {previous_encounter.raw_input or "No raw input available."}

                        Latest Final Note:
                        {latest_final_note.note_text if latest_final_note else "No previous final note available."}
            """
        )

    previous_history = "\n\n---\n\n".join(previous_history_blocks)

    if not previous_history:
        previous_history = "No previous encounter history available."

    prompt = f"""
            You are an AI clinical scribe.

            Generate a SOAP note for the current patient encounter.

            Patient Information:
            - First Name: {patient.first_name}
            - Last Name: {patient.last_name}
            - Date of Birth: {patient.date_of_birth}

            1. Current Raw Input:
            {encounter.raw_input or "No raw input provided."}

            2. Previous Patient History, sorted by encounter updated time:
            {previous_history}

            3. Specific Instruction / Prompt Template:
            Template Name: {template.name}
            Encounter Type: {template.encounter_type}

            {template.prompt_text}

            4. Required Output Format:
            The output must be a SOAP note and must include all of the following sections:

            Subjective:
            - Patient-reported symptoms, history, concerns, and relevant context.

            Objective:
            - Observable findings, exam details, vitals, labs, imaging, or other objective data if available.
            - If information is not provided, state that it was not provided.

            Assessment:
            - Clinical assessment based on the current raw input and relevant previous history.
            - Include at least one suggested ICD-10 code and its description.
            - Format ICD-10 suggestions clearly, for example:
            - ICD-10: R05.9 — Cough, unspecified

            Plan:
            - Recommended next steps, treatment plan, follow-up, patient education, or additional workup.

            Important Rules:
            - Do not invent facts that are not supported by the provided input.
            - If something is missing, say it was not provided.
            - Use the previous history only as supporting context.
            - Keep the note clinically concise and professional.
            """

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt,
    )

    return response.output_text



def build_prompt(encounter_id, template_id):
    encounter = (
        Encounter.objects
        .select_related("patient", "provider")
        .get(id=encounter_id)
    )

    template = NoteTemplate.objects.get(id=template_id, is_active=True)
    patient = encounter.patient

    previous_encounters = (
        Encounter.objects
        .filter(patient=patient)
        .exclude(id=encounter.id)
        .order_by("updated_at")
    )

    previous_blocks = []

    for prev in previous_encounters:
        latest_note_version = (
            prev.versions
            .order_by("-saved_at")
            .first()
        )

        previous_blocks.append(f"""
            Encounter ID: {prev.id}
            Updated At: {prev.updated_at}

            Previous Raw Input:
            {prev.raw_input or "No raw input available."}

            Latest Saved Note:
            {latest_note_version.note_text if latest_note_version else "No saved note available."}
            """)

    previous_history = "\n\n---\n\n".join(previous_blocks)

    if not previous_history:
        previous_history = "No previous encounter history available."

    prompt = f"""
            You are an AI clinical scribe.

            Generate a structured SOAP note for the current encounter.

            Patient Information:
            - First Name: {patient.first_name}
            - Last Name: {patient.last_name}
            - Date of Birth: {patient.date_of_birth}

            1. Current Raw Input:
            {encounter.raw_input or "No current raw input provided."}

            2. Previous Patient History, sorted by time:
            {previous_history}

            3. Specific Instruction / Prompt Template:
            Template Name: {template.name}
            Encounter Type: {template.encounter_type}

            {template.prompt_text}

            4. Required Output Format:

            The output must be a SOAP note with these sections:

            Subjective:
            Objective:
            Assessment:
            Plan:

            The Assessment section must include at least one suggested ICD-10 code and description.

            Format ICD-10 codes exactly like this:
            - R50.9: Fever, unspecified

            Do not bold ICD-10 codes.
            Do not write "**ICD-10:**".
            Do not use markdown bold anywhere in the SOAP note.
            Do not use em dashes for ICD-10 codes.

            Rules:
            - Do not invent facts.
            - If information is missing, say it was not provided.
            - Use previous history only as supporting context.
            - Keep the note clinically concise and professional.
            """

    return prompt



def stream_llm(encounter_id, template_id):
    prompt = build_prompt(encounter_id, template_id)

    stream = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt,
        stream=True,
    )

    for event in stream:
        if getattr(event, "type", None) == "response.output_text.delta":
            yield event.delta




def search_code(text, top_k=5):

    if not text or not text.strip():
        return []

    project_root = Path(__file__).resolve().parents[2]
    subset_path = project_root / "icd-10" / "icd10_subset.json"

    if not subset_path.exists():
        raise FileNotFoundError(f"Could not find ICD-10 subset file: {subset_path}")

    with open(subset_path, "r", encoding="utf-8") as f:
        codes = json.load(f)

    code_text = "\n".join(
        f"{item['code']}: {item['description']}"
        for item in codes
    )

    prompt = f"""
            You are an ICD-10-CM search assistant.

            The provider searched for:
            {text}

            Choose the top {top_k} most relevant ICD-10-CM diagnosis codes from the local list below.

            Rules:
            - Only choose codes from the provided local list.
            - Do not invent new ICD-10 codes.
            - Return only JSON.
            - Do not include explanation.

            Return format:
            [
            {{"code": "CODE", "description": "DESCRIPTION"}}
            ]

            Local ICD-10-CM list:
            {code_text}
            """

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt,
    )

    output_text = response.output_text.strip()

    try:
        results = json.loads(output_text)
    except json.JSONDecodeError:
        return []

    valid_codes = {
        item["code"]: item["description"]
        for item in codes
    }

    cleaned_results = []

    for item in results:
        code = item.get("code")

        if code in valid_codes:
            cleaned_results.append({
                "code": code,
                "description": valid_codes[code]
            })

    return cleaned_results[:top_k]