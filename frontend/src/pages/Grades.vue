<template>
  <div class="px-5 py-4">
    <Dropdown v-if="allPrograms.length" class="mb-4" :options="allPrograms">
      <template #default="{ open }">
        <Button :label="selectedProgram">
          <template #suffix><FeatherIcon :name="open ? 'chevron-up' : 'chevron-down'" class="h-4 text-gray-600" /></template>
        </Button>
      </template>
    </Dropdown>
    <ListView v-if="tableData.rows.length" :columns="tableData.columns" :rows="tableData.rows"
      :options="{ selectable: false, showTooltip: false }" row-key="id" />
    <MissingData v-else message="No grades found" />
  </div>
</template>
<script setup>
import { Dropdown, FeatherIcon, ListView, createResource } from 'frappe-ui'
import { ref, watch } from 'vue'
import { studentStore } from '@/stores/student'
import MissingData from '@/components/MissingData.vue'

const { getCurrentProgram, getStudentInfo } = studentStore()
const student = getStudentInfo().value
const selectedProgram = ref(getCurrentProgram().value?.program || '')
const allPrograms = ref([])
const tableData = ref({ columns: [], rows: [] })
const grades = createResource({
  url: 'education.education.api.get_student_grades',
  makeParams() { return { student: student.name, program: selectedProgram.value } },
  onSuccess(scores) {
    const exams = [...new Set(scores.map(row => row.assessment_group))]
    const courses = [...new Set(scores.map(row => row.course))]
    tableData.value = {
      columns: [{ label: 'Course', key: 'course' }, { label: 'Batch', key: 'batch' }, ...exams.map(exam => ({ label: exam, key: exam }))],
      rows: courses.map(course => {
        const entries = scores.filter(row => row.course === course)
        const result = { id: course, course, batch: entries[0].student_batch }
        for (const exam of exams) {
          const rows = entries.filter(row => row.assessment_group === exam)
          result[exam] = rows.length ? `${rows.reduce((sum, row) => sum + row.score, 0)}/${rows.reduce((sum, row) => sum + row.maximum_score, 0)}` : '-'
        }
        return result
      }),
    }
  },
  auto: true,
})
createResource({
  url: 'education.education.api.get_student_programs',
  params: { student: student.name },
  onSuccess(programs) {
    allPrograms.value = programs.map(row => ({ label: row.program, onClick: () => { selectedProgram.value = row.program } }))
    if (!selectedProgram.value && programs.length) selectedProgram.value = programs[0].program
  },
  auto: true,
})
watch(selectedProgram, () => grades.reload())
</script>
